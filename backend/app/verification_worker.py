"""One bounded catalog review at a time, with durable refresh and discovery leases."""
import argparse
import logging
import os
import signal
import threading
import time
from datetime import date
from pathlib import Path

from . import auto_verification, db, discovery, live_discovery, verification_store as store

log = logging.getLogger(__name__)


def enabled():
    return os.environ.get('VERIFICATION_PIPELINE_ENABLED', '').lower() in ('1', 'true', 'yes')


def bounded_interval(name, default):
    return min(604800, max(3600, int(os.environ.get(name, str(default)))))


def next_capability(conn, catalog):
    """Round robin across declared tasks; new tasks receive a first turn immediately."""
    runs = dict(conn.execute("SELECT substr(name,11),updated FROM verification_schedule WHERE name LIKE 'discovery:%'"))
    capabilities = sorted({cap for category in catalog.categories for cap in category.capabilities})
    return min(capabilities, key=lambda cap: (runs.get(cap, 0), cap)) if capabilities else None


def scheduled_discovery(conn, finder, now=None):
    if os.environ.get('SCHEDULED_DISCOVERY_ENABLED', '').lower() not in ('1','true','yes'):
        return None
    interval = bounded_interval('DISCOVERY_INTERVAL_S', 86400)
    lease = store.schedule_claim(conn, 'discovery', now=now, ttl=120)
    if lease is None:
        return None
    code = 'budget_paused'
    query=None
    try:
        if not finder.available():
            return code
        catalog = db.read_catalog(conn)
        capability = next_capability(conn, catalog)
        if capability is None:
            code = 'no_tasks'; return code
        if callable(getattr(finder, 'update_catalog', None)):
            finder.update_catalog(catalog)
        request = discovery.DiscoveryRequest(capability=capability, max_results=2, max_pages=8, time_budget_s=25)
        query=store.query_claim(conn,request,now=now)
        if query['state']!='claimed':
            code='query_'+query['state'];return code
        result = discovery.run_finder(catalog, request, finder)
        # Refresh the view after the slow search so duplicate checking sees concurrent imports.
        report = discovery.store(conn, db.read_catalog(conn), request, result, date.today())
        store.query_finish(conn,query,report,now=now)
        query=None
        store.enqueue(conn, store.source_tools(conn))
        stamp = time.time() if now is None else now
        with conn:
            conn.execute("INSERT INTO verification_schedule(name,due,runs,code,updated) VALUES(?,?,1,?,?) ON CONFLICT(name) DO UPDATE SET runs=runs+1,code=excluded.code,updated=excluded.updated",
                         ('discovery:'+capability, stamp+interval, report.status, stamp))
        code = 'completed'
        return code
    except discovery.DiscoveryFailed:
        code = 'search_unavailable'; return code
    except Exception as exc:
        code = 'discovery_failed'
        log.warning('Scheduled discovery failed: %s', type(exc).__name__)
        return code
    finally:
        if query and query['state']=='claimed':
            store.query_finish(conn,query,now=now)
        store.schedule_finish(conn, 'discovery', lease, code, interval=interval, now=now)


def review_one(conn, search, cancel=None, reviewer=None):
    store.enqueue(conn, store.source_tools(conn))
    job = store.claim(conn, ttl=150)
    if job is None:
        return None
    outcome, reason, checked = 'retry', 'review_interrupted', None
    try:
        source = next((tool for tool in store.source_tools(conn) if tool.id == job['tool_id']), None)
        if source is None:
            outcome, reason = 'blocked', 'source_removed'
        else:
            checked = (reviewer or auto_verification.review)(source, job['capability'], db.read_catalog(conn), search, cancel)
            outcome = 'verified' if checked.auto_review and checked.auto_review.eligible else 'partial'
            reason = 'evidence_confirmed' if outcome == 'verified' else 'incomplete_evidence'
            if checked.auto_review and not checked.auto_review.eligible and any(
                    value=='true' for value in checked.auto_review.evidence.get('conflicts',{}).values()):
                reason='contradictory_evidence'
            if checked.auto_review and not checked.auto_review.checks.get('official_page_fetched', True):
                outcome, reason = 'blocked', 'official_page_unavailable'
    except Exception as exc:
        if str(exc) == 'verification_budget_unavailable':
            outcome, reason = 'budget_paused', 'provider_limit_reached'
        else:
            reason = 'review_'+type(exc).__name__.lower()
            log.warning('Catalog review failed for %s/%s: %s', job['tool_id'], job['capability'], type(exc).__name__)
    published = store.finish(conn, job, checked, outcome, reason,
                             refresh_s=bounded_interval('VERIFICATION_REFRESH_S', 86400))
    log.info('Catalog review %s/%s: %s; lease accepted=%s', job['tool_id'], job['capability'], outcome, published)
    return {'tool_id':job['tool_id'], 'capability':job['capability'], 'outcome':outcome, 'published':published}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--max-jobs', type=int, default=1)
    args = parser.parse_args()
    if not enabled():
        raise SystemExit('VERIFICATION_PIPELINE_ENABLED must be enabled explicitly')
    if not 1 <= args.max_jobs <= 256:
        raise SystemExit('max-jobs must be between 1 and 256')
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    path = Path(os.environ['APP_DB_PATH'])
    conn = db.connect(path)
    search = live_discovery.OpenRouterSearch(path.with_name('discovery-spend.db'), [])
    finder = live_discovery.make_finder(db.read_catalog(conn), path.with_name('discovery.db'))
    try:
        count = 0
        while not stop.is_set():
            with conn:
                stamp=time.time()
                conn.execute("INSERT INTO verification_schedule(name,due,code,updated) VALUES('worker',?,'alive',?) ON CONFLICT(name) DO UPDATE SET due=excluded.due,code=excluded.code,updated=excluded.updated",(stamp+240,stamp))
            # Reviews take precedence. A discovery run never consumes a renderer slot.
            result = review_one(conn, search, stop)
            if result:
                count += 1
            if not stop.is_set():
                scheduled_discovery(conn, finder)
            if args.once and (count >= args.max_jobs or result is None):
                break
            stop.wait(2 if result else 15)
    finally:
        finder.close()
        conn.close()


if __name__ == '__main__':
    main()
