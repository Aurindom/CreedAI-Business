import json

import httpx
import pytest

from app.live_discovery import OpenRouterSearch
from app.discovery_worker.sources import SearchContext, SearchQuery


@pytest.mark.parametrize('engine', ['exa', 'native'])
def test_search_engine_is_explicit_and_actual_cost_is_settled(tmp_path, monkeypatch, engine):
    monkeypatch.setenv('DISCOVERY_WEB_ENGINE', engine)
    monkeypatch.setenv('DISCOVERY_OPENROUTER_KEY', 'synthetic-private-provider-key')
    original = httpx.Client
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'usage': {'cost': 0.01}, 'choices': [{'message': {
            'content': json.dumps([{'url': 'https://vendor.example/product', 'title': 'Software'}])}}]})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    search = OpenRouterSearch(tmp_path/'spend.db', [])
    assert search.source_id == 'openrouter-' + engine + '-live'
    assert search.search(SearchQuery('invoicing', None, {}, 2), SearchContext(20))
    assert calls[0]['plugins'][0]['engine'] == engine
    assert search.ledger.status()['committed_usd'] == .01


def test_failed_search_is_diagnosable_without_logging_private_provider_body(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('DISCOVERY_OPENROUTER_KEY', 'synthetic-private-provider-key')
    original = httpx.Client
    def handler(request):
        return httpx.Response(500, json={'error': {'message': 'PRIVATE-PROVIDER-BODY'}})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    search = OpenRouterSearch(tmp_path/'spend.db', [])
    with pytest.raises(RuntimeError):
        search.search(SearchQuery('invoicing', None, {}, 2), SearchContext(20))
    state = search.ledger.status()
    assert state['tripped'] == 'search_http_500'
    assert state['by_state']['held']['usd'] == .25
    assert not search.available()
    assert 'PRIVATE-PROVIDER-BODY' not in caplog.text
    assert 'synthetic-private-provider-key' not in caplog.text
    record = next(r for r in caplog.records if r.message == 'discovery_search_failed')
    assert record.provider_status == 500
    from app.logging_config import SafeFormatter
    assert json.loads(SafeFormatter().format(record))['provider_status'] == 500


def test_unknown_engine_cannot_silently_switch_provider(tmp_path, monkeypatch):
    monkeypatch.setenv('DISCOVERY_WEB_ENGINE', 'random')
    with pytest.raises(ValueError, match='invalid_discovery_web_engine'):
        OpenRouterSearch(tmp_path/'spend.db', [])


def test_native_citation_leads_survive_prose_without_trusting_product_facts(tmp_path, monkeypatch):
    monkeypatch.setenv('DISCOVERY_OPENROUTER_KEY', 'synthetic-key')
    original = httpx.Client
    def handler(request):
        return httpx.Response(200, json={'usage': {'cost': .02}, 'choices': [{'message': {
            'content': 'I found this software. Invented price: $99.',
            'annotations': [{'type': 'url_citation', 'url_citation': {'url': 'https://vendor.example/product', 'title': 'Product'}},
                            {'type': 'url_citation', 'url_citation': {'url': 'http://127.0.0.1/private'}}]}}]})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    search = OpenRouterSearch(tmp_path/'spend.db', [])
    hits = search.search(SearchQuery('invoicing', None, {}, 2), SearchContext(20))
    assert [(h.url, h.title) for h in hits] == [('https://vendor.example/product', 'Product')]
    assert search.ledger.status()['committed_usd'] == .02


def test_native_single_json_lead_block_after_commentary_is_not_a_factual_answer(tmp_path, monkeypatch):
    monkeypatch.setenv('DISCOVERY_OPENROUTER_KEY', 'synthetic-key')
    original = httpx.Client
    def handler(request):
        content = 'Search results (untrusted facts):\n\n```json\n' + json.dumps([
            {'url': 'https://vendor.example/product', 'title': 'Product', 'price': 999}]) + '\n```'
        return httpx.Response(200, json={'usage': {'cost': .02}, 'choices': [{'message': {'content': content}}]})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    search = OpenRouterSearch(tmp_path/'spend.db', [])
    hits = search.search(SearchQuery('invoicing', None, {}, 2), SearchContext(20))
    assert [(h.url, h.title) for h in hits] == [('https://vendor.example/product', 'Product')]
    assert not hasattr(hits[0], 'price')
