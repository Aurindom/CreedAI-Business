"""Live search adapter for the existing bounded discovery worker and app validator."""
from __future__ import annotations

import os
import re
import json
import threading
import logging
from pathlib import Path
from urllib.parse import quote_plus
from xml.etree import ElementTree

from .discovery_worker.contract import Snapshot
from .discovery_worker.discovery import Deps, discover_tools
from .discovery_worker.sources import Budget, Hit, HttpxTransport, SafeFetcher, system_resolver
from .discovery_worker.store import Store
from .schemas import Catalog

logger = logging.getLogger(__name__)


class OpenRouterSearch:
    """Search leads are untrusted; only independently fetched vendor evidence is stored."""
    source_id = 'openrouter-live'
    kind = 'live'

    def __init__(self, state: Path, names: list[str]):
        from .model_gateway import Ledger
        self.ledger = Ledger(state)
        # App and background verifier share this ledger; a fresh reservation
        # belongs to a live process and must not be mistaken for an orphan.
        self.ledger.recover(stale_after_s=120)
        self.names = names
        self.engine = os.environ.get('DISCOVERY_WEB_ENGINE', 'native').strip().lower()
        if self.engine not in ('exa', 'native'):
            raise ValueError('invalid_discovery_web_engine')
        self.source_id = 'openrouter-' + self.engine + '-live'
        self.max_requests = min(256, max(1, int(os.environ.get('DISCOVERY_MAX_REQUESTS', '4'))))
        self.cap_usd = min(2.0, max(0.0, float(os.environ.get('DISCOVERY_SPEND_CAP_USD', '1'))))

    def search(self, query, context):
        import httpx
        from .chat import usage_cost
        from .agent.grounding import extract_json
        key = os.environ.get('DISCOVERY_OPENROUTER_KEY') or os.environ.get('OPENROUTER_API_KEY')
        if not key:
            raise RuntimeError('discovery_search_not_configured')
        number, reason = self.ledger.admit(0.25, self.max_requests, self.cap_usd)
        if number is None:
            raise RuntimeError('discovery_search_budget_unavailable')
        body = {'model': 'anthropic/claude-haiku-4.5', 'max_tokens': 1200, 'temperature': 0,
                'provider': {'allow_fallbacks': False, 'max_price': {'prompt': 1, 'completion': 5}},
                'usage': {'include': True},
                'plugins': [{'id': 'web', 'engine': self.engine, 'mode': 'fast', 'max_results': 3}],
                'messages': [{'role': 'system', 'content': 'Search the live web. Return ONLY a JSON array of up to three '
                              'objects with url and title, naming official product pages for business software or AI '
                              'services that perform the task. Prefer clear plan inclusion and transparent monthly or free pricing. '
                              'No reviews, hardware, directories, rankings or prose. '
                              'Do not invent product facts; pages will be fetched independently.'},
                             {'role': 'user', 'content': query.capability.replace('_', ' ') + ' for small businesses. '
                              'Find alternatives absent from this existing catalog: ' + json.dumps(self.names)}]}
        try:
            with httpx.Client(timeout=min(20, context.remaining_s), follow_redirects=False) as client:
                response = client.post('https://openrouter.ai/api/v1/chat/completions', json=body,
                                       headers={'Authorization': 'Bearer '+key})
                response.raise_for_status()
                data = response.json()
            cost = usage_cost(data.get('usage'))
            if cost is None or cost > 0.25:
                self.ledger.hold(number, 'search_usage_unverified', cost)
                raise RuntimeError('search_usage_unverified')
            self.ledger.settle(number, cost)
            message = data['choices'][0]['message']
            try:
                output = json.loads(extract_json(message.get('content') or ''))
            except ValueError:
                output = None
            if not isinstance(output, list):
                # Discovery accepts one structured lead block inside search
                # commentary. This parser is intentionally separate from the
                # strict Penny factual-answer parser: only URLs/titles survive.
                blocks = re.findall(r'```(?:json)?\s*\n(.*?)\n```', message.get('content') or '', re.S)
                if len(blocks) == 1:
                    try:
                        output = json.loads(blocks[0])
                    except ValueError:
                        pass
            if not isinstance(output, list):
                # Native search can attach citations while returning prose or
                # truncated JSON. Citation URLs are search LEADS only: the
                # guarded fetcher and verifier must still prove every fact.
                output = [entry['url_citation'] for entry in message.get('annotations', [])
                          if isinstance(entry, dict) and isinstance(entry.get('url_citation'), dict)]
                if not output:
                    raise ValueError('invalid_search_results')
            return [Hit(row['url'], str(row.get('title', ''))[:160]) for row in output[:5]
                    if isinstance(row, dict) and isinstance(row.get('url'), str)
                    and row['url'].startswith('https://')]
        except Exception as exc:
            # Never log provider bodies, headers, prompts or exception strings.
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            logger.warning('discovery_search_failed', extra={'search_engine': self.engine,
                'provider_status': status, 'failure_type': type(exc).__name__})
            # Already-settled usage is retained; an ambiguous in-flight charge stays reserved.
            with self.ledger._tx() as conn:
                state = conn.execute('SELECT state FROM attempt WHERE n=?', (number,)).fetchone()[0]
            if state == 'reserved':
                self.ledger.hold(number, 'search_http_' + str(status) if status else 'search_failed')
            raise RuntimeError('live_search_failed') from None

    def available(self):
        status = self.ledger.status()
        return (bool(os.environ.get('DISCOVERY_OPENROUTER_KEY') or os.environ.get('OPENROUTER_API_KEY'))
                and not status['tripped'] and status['attempts'] < self.max_requests
                and status['committed_usd'] + 0.25 <= self.cap_usd)


class BingSearch:
    source_id = 'bing-public-rss'
    kind = 'live'

    def __init__(self, fetcher: SafeFetcher):
        self.fetcher = fetcher

    def search(self, query, context):
        text = '"' + query.capability.replace('_', ' ') + '" AI software small business'
        budget = Budget(max_pages=1, time_budget_s=min(8.0, context.remaining_s),
                        max_bytes_per_page=200_000, max_retries=0, cancel=context.cancel)
        page = self.fetcher.fetch('https://www.bing.com/search?format=rss&q=' + quote_plus(text), budget)
        root = ElementTree.fromstring(page.text)
        return [Hit(item.findtext('link', ''), item.findtext('title', ''))
                for item in root.findall('./channel/item')][:query.limit]


def make_finder(catalog: Catalog, state: Path):
    # Reuse the worker with the current catalog vocabulary, not its old frozen fixture snapshot.
    snapshot = Snapshot(catalog.model_dump(mode='json'), {'contract_version': '1.1.0'})
    fetcher = SafeFetcher(HttpxTransport(user_agent='MainStreetAI-Research/1.0'), system_resolver, request_timeout_s=5)
    searches = ([OpenRouterSearch(state.with_name('discovery-spend.db'), [tool.name for tool in catalog.tools])]
                if os.environ.get('DISCOVERY_SEARCH_PROVIDER') == 'openrouter' else [BingSearch(fetcher)])
    deps = Deps(snapshot, searches, fetcher, Store(state), kind='live')

    def find(request, cancel: threading.Event):
        result = discover_tools(request.model_dump(mode='json'), deps, cancel)
        # A task verb on a hardware/blog page is not evidence of an offered business service.
        for candidate in result.get('candidates', []):
            supplied = [row for row in candidate.get('evidence', [])
                        if row.get('field') == 'capability.' + request.capability]
            if not any(re.search(r'\b(software|platform|automation|automated|ai|agent|receptionist|service|business(?:es)?)\b',
                                 row.get('excerpt', ''), re.I) for row in supplied):
                candidate['capabilities'] = [cap for cap in candidate.get('capabilities', []) if cap != request.capability]
                candidate['evidence'] = [row for row in candidate.get('evidence', []) if row not in supplied]
        return result

    find.close = deps.store.conn.close
    find.available = searches[0].available if isinstance(searches[0], OpenRouterSearch) else lambda: True
    if isinstance(searches[0], OpenRouterSearch):
        from . import auto_verification
        find.review = lambda tool, capability, current: auto_verification.review(tool, capability, current, searches[0])
        find.update_catalog = lambda current: setattr(searches[0], 'names', [tool.name for tool in current.tools])

    return find


def enabled():
    return os.environ.get('DISCOVERY_ENABLED', '').lower() in ('1', 'true', 'yes')
