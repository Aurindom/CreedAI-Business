import copy
import sqlite3
import time
from datetime import date

import pytest

from app import auto_verification, db, verification_store as store, verification_worker as worker
from app.agent import tool_execution
from app.schemas import AutomaticReview, Capability, Fact, Tool
from app.pricing_blocks import blocks_from_html, qualified_plan
from app.verification_pages import Pages

URL='https://example.com/pricing'


def source():
    return Tool(id='new-ledger',name='New Ledger',url=URL,trades=[],origin='discovered',summary='Candidate',
                capabilities=[Capability(capability='bookkeeping',access=Fact(status='unknown')),Capability(capability='phone',access=Fact(status='unknown'))])


def reviewed(tool,cap='bookkeeping',price=12):
    def f(value):return Fact(status='present',value=value,source_url=URL,source_type='vendor',checked=date.today())
    result=tool.model_copy(deep=True)
    result.capability(cap).access=f('included')
    result.capability(cap).included_from=f('Core' if cap=='bookkeeping' else 'Voice')
    result.plan_tiers=f(['Core' if cap=='bookkeeping' else 'Voice'])
    result.plan_prices=f({result.capability(cap).included_from.value:price})
    result.entry_billing=f('monthly')
    result.auto_review=AutomaticReview(checked=date.today(),capability=cap,checks={'supported':True},eligible=True,sources=[URL],notes=[])
    result.status='verified'
    return result


@pytest.fixture
def connection(tmp_path,catalog):
    conn=db.connect(tmp_path/'catalog.db');db.seed(conn,catalog);db.add_discovered_tool(conn,source())
    yield conn
    conn.close()


def test_all_scopes_idempotent_and_single_global_lease(connection,tmp_path):
    count=store.enqueue(connection,store.source_tools(connection),now=10)
    assert count>2 and store.enqueue(connection,store.source_tools(connection),now=11)==0
    first=store.claim(connection,now=12,ttl=20)
    other=db.connect(tmp_path/'catalog.db')
    assert store.claim(other,now=13) is None
    later=store.claim(other,now=33)
    assert later and later['lease']!=first['lease']
    assert not store.finish(connection,first,now=34)
    assert store.finish(other,later,now=34)
    other.close()


def test_scope_prices_survive_seed_and_do_not_invent_plan_hierarchy(connection,catalog):
    tool=source();store.enqueue(connection,[tool],now=10)
    one=store.claim(connection,now=11)
    assert store.finish(connection,one,reviewed(tool),outcome='verified',now=12,refresh_s=1000)
    two=store.claim(connection,now=13)
    assert store.finish(connection,two,reviewed(tool,'phone',44),outcome='verified',now=14,refresh_s=1000)
    db.seed(connection,catalog)
    live=store.apply_overlays(connection,[tool],now=15)[0]
    assert live.capability('bookkeeping').verified_plan_prices.value=={'Core':12}
    assert live.capability('phone').verified_plan_prices.value=={'Voice':44}
    assert live.plan_rank('Core') is None and live.plan_rank('Voice') is None
    assert live.reviews['bookkeeping'].eligible and live.reviews['phone'].eligible
    expired=store.apply_overlays(connection,[tool],now=1015)[0]
    assert not expired.reviews['phone'].eligible


def test_old_input_cannot_publish_and_new_input_is_queued(connection):
    tool=source();store.enqueue(connection,[tool],now=10);job=store.claim(connection,now=11)
    changed=Tool.model_validate({**tool.model_dump(),'url':'https://example.com/new'})
    db.add_discovered_tool(connection,changed)
    assert not store.finish(connection,job,reviewed(tool),outcome='verified',now=12)
    assert not connection.execute('SELECT 1 FROM verification_overlay').fetchone()
    assert store.enqueue(connection,[changed],now=13)==2


def test_removed_capability_retires_its_job_without_changing_other_scopes(connection):
    tool=source();store.enqueue(connection,[tool],now=10)
    changed=tool.model_copy(update={'capabilities':[tool.capability('phone')]})
    db.add_discovered_tool(connection,changed)
    assert store.enqueue(connection,[changed],now=12)==1
    assert connection.execute("SELECT state FROM verification_job WHERE tool_id=? AND capability='bookkeeping'",(tool.id,)).fetchone()[0]=='retired'
    assert store.claim(connection,now=13)['capability']=='phone'


def test_partial_review_keeps_live_approved_scope_until_expiry(connection):
    tool=source();store.enqueue(connection,[tool],now=10);job=store.claim(connection,now=11)
    store.finish(connection,job,reviewed(tool),outcome='verified',now=12,refresh_s=100)
    store.enqueue(connection,[tool],now=13,force=True);job=store.claim(connection,now=14)
    partial=tool.model_copy(update={'auto_review':AutomaticReview(checked=date.today(),capability='bookkeeping',eligible=False,checks={'plan':False},notes=[],sources=[])})
    store.finish(connection,job,partial,outcome='partial',now=15)
    assert store.apply_overlays(connection,[tool],now=16)[0].reviews['bookkeeping'].eligible
    assert not store.apply_overlays(connection,[tool],now=113)[0].reviews['bookkeeping'].eligible


def test_worker_error_and_exhausted_budget_preserve_queue_and_source(connection):
    def fail(*args):raise RuntimeError('verification_budget_unavailable')
    outcome=worker.review_one(connection,None,reviewer=fail)
    assert outcome['outcome']=='budget_paused' and outcome['published']
    assert store.status(connection)['states']['budget_paused']==1
    assert db.read_catalog(connection).tool('new-ledger').summary=='Candidate'


def test_schedule_has_one_lease_and_durable_daily_due(connection):
    lease=store.schedule_claim(connection,'discovery',now=100)
    assert lease and store.schedule_claim(connection,'discovery',now=101) is None
    assert store.schedule_finish(connection,'discovery',lease,'completed',now=102,interval=86400)
    assert store.schedule_claim(connection,'discovery',now=103) is None
    assert not store.schedule_finish(connection,'discovery',lease,'completed',now=104)
    assert store.schedule_claim(connection,'discovery',now=86503)


def test_schedule_task_rotation_uses_recorded_runs(connection,catalog):
    first=worker.next_capability(connection,catalog)
    with connection:connection.execute('INSERT INTO verification_schedule(name,due,updated) VALUES(?,?,?)',('discovery:'+first,100,100))
    assert worker.next_capability(connection,catalog)!=first


def test_registered_mcp_read_uses_turn_snapshot_when_background_catalog_changes(connection,catalog):
    run,operations=tool_execution.register(connection,None,catalog,['ledger'],30)
    later=catalog.model_copy(deep=True);later.tool('ledger').name='Updated Ledger'
    receipt=tool_execution.execute(connection,later,operations[0].label,'ledger')
    assert receipt['success'] and receipt['tool']['name']=='Ledger'
    assert tool_execution.verify(connection,None,catalog,run,operations).ok
    assert not tool_execution.verify(connection,None,later,run,operations).ok


@pytest.mark.parametrize('cell,accepted',[('Included',True),('Yes',True),('✓',True),('',False),('No',False),('Not included',False),('✗',False)])
def test_pricing_columns_keep_price_and_inclusion_in_same_tier(cell,accepted):
    html=f'<table><tr><th>Feature</th><th>Core</th><th>Pro</th></tr><tr><td>Price</td><td>USD 12 monthly</td><td>USD 44 monthly</td></tr><tr><td>Bookkeeping</td><td>{cell}</td><td>Included</td></tr></table>'
    blocks=blocks_from_html(html,URL)
    assert bool(qualified_plan(blocks[0],['bookkeeping']))==accepted
    assert qualified_plan(blocks[1],['bookkeeping'])['price_usd_monthly']==44


@pytest.mark.parametrize('price',['$12 monthly','USD 12 annually','USD 12 per user monthly','Free trial','Free onboarding','USD 12 monthly setup fee','USD 12 monthly or USD 90 annually','USD , monthly','USD 1,,23 monthly','USD 1,23 monthly','USD 12 per minute monthly','USD 12 monthly plus $0.10 overage','USD 12 monthly, another tier $90'])
def test_ambiguous_billing_never_verified(price):
    block=blocks_from_html(f'<section class="pricing"><h3>Core</h3>{price}<p>Includes bookkeeping</p></section>',URL)
    if block:assert qualified_plan(block[0],['bookkeeping']) is None


def test_hidden_parent_pricing_not_used():
    assert not blocks_from_html('<div hidden><section class="pricing"><h3>Core</h3>USD 1 monthly includes bookkeeping</section></div>',URL)


def test_structural_pricing_promotes_exact_scope_and_retains_block_receipt(catalog):
    pages=Pages();pages[URL]='Software for small businesses. Includes bookkeeping.'
    pages.blocks=blocks_from_html('<div class="pricing"><h3>Core</h3>USD 12 monthly. Includes bookkeeping.</div>',URL)
    blank={'feature':{'value':False,'url':None,'quote':''},'business_fit':{'value':False,'url':None,'quote':''},
           'plan':{'name':None,'price_usd_monthly':None,'billing':'not_stated','included':False,'url':None,'quote':''}}
    checked=auto_verification.evaluate(source(),'bookkeeping',catalog,pages,blank)
    assert checked.auto_review.eligible
    assert checked.auto_review.evidence['plan']['basis']=='same_pricing_block'


def test_provider_recovery_does_not_orphan_other_process_live_reservation(tmp_path):
    from app.model_gateway import Ledger
    ledger=Ledger(tmp_path/'spend.db');number,_=ledger.admit(.25,5,1)
    assert ledger.recover(stale_after_s=120)==0
    ledger.settle(number,.001)
    assert not ledger.status()['tripped']


def test_identical_research_uses_cache_and_one_cross_process_lease(connection):
    from app.discovery import DiscoveryRequest,DiscoveryReport
    request=DiscoveryRequest(capability='bookkeeping')
    one=store.query_claim(connection,request,now=10)
    assert one['state']=='claimed'
    assert store.query_claim(connection,request,now=11)['state']=='busy'
    report=DiscoveryReport(run_id='test-run',status='completed')
    assert store.query_finish(connection,one,report,now=12)
    cached=store.query_claim(connection,request,now=13)
    assert cached['state']=='cached' and cached['doc']['run_id']=='test-run'
    assert store.query_claim(connection,request,now=3613)['state']=='claimed'
    assert not store.query_finish(connection,one,report,now=3614)


def test_single_offering_and_existing_tiers_do_not_break_scoped_verification(catalog):
    from conftest import fact
    pages=Pages();pages[URL]='Software for small businesses. Includes bookkeeping.'
    pages.blocks=blocks_from_html('<div class="pricing"><h3>Core</h3>USD 12 monthly. Includes bookkeeping.</div>',URL)
    blank={'feature':{'value':False,'url':None,'quote':''},'business_fit':{'value':False,'url':None,'quote':''},
           'plan':{'name':None,'price_usd_monthly':None,'billing':'not_stated','included':False,'url':None,'quote':''}}
    tool=source();tool.entry_plan=fact('Legacy');tool.capability('phone').access=fact('included');tool.capability('phone').included_from=fact('Legacy')
    checked=auto_verification.evaluate(tool,'bookkeeping',catalog,pages,blank)
    assert checked.auto_review.eligible and set(checked.plan_tiers.value)=={'Legacy','Core'}
    tool.offering=fact('single')
    checked=auto_verification.evaluate(tool,'bookkeeping',catalog,pages,blank)
    assert checked.auto_review.eligible and not checked.plan_tiers.known
    assert checked.capability('bookkeeping').verified_plan_prices.value=={'Core':12}


def test_canonical_product_urls_keep_distinct_products_and_strip_tracking():
    from app.domains import canonical_product_url
    assert canonical_product_url('https://www.example.com/product/?utm_source=ad')==canonical_product_url('https://example.com/product')
    assert canonical_product_url('https://example.com/product/a')!=canonical_product_url('https://example.com/product/b')
    assert canonical_product_url('https://example.com/?product=a')!=canonical_product_url('https://example.com/?product=b')


def test_functional_review_phrase_is_not_misclassified_as_testimonial():
    from app.discovery_worker.extract import phrase_regex,scan_phrase,_Parser
    pattern=phrase_regex('review replies')
    assert scan_phrase('our platform automates review replies for small businesses.',pattern)[0]
    assert not scan_phrase('customers say: "we love review replies".',pattern)[0]
    assert not scan_phrase('our platform does not support review replies.',pattern)[0]
    parser=_Parser();parser.feed('<nav><a href="/pricing">Pricing plans</a></nav><p>Our software</p>')
    assert parser.links==[('/pricing','Pricing plans')]
    assert 'Pricing plans' not in ' '.join(parser.text)


def test_operator_sweep_rejects_unauthenticated_and_is_idempotent(client,monkeypatch):
    monkeypatch.setenv('VERIFICATION_PIPELINE_ENABLED','true')
    monkeypatch.setenv('DISCOVERY_TOKEN','operator-'+'x'*32)
    assert client.post('/api/verification/sweep',json={}).status_code==401
    auth={'Authorization':'Bearer operator-'+'x'*32}
    first=client.post('/api/verification/sweep',json={},headers=auth)
    assert first.status_code==200 and first.json()['queued']>0
    assert client.post('/api/verification/sweep',json={},headers=auth).json()['queued']==0
    status=client.get('/api/verification/status').json()
    assert status['enabled'] and status['scopes']==first.json()['queued']
    assert client.post('/api/verification/sweep',json={'tool_id':'missing'},headers=auth).status_code==404


def test_pipeline_deduplicates_changed_headline_and_keeps_prior_capabilities(tmp_path,monkeypatch):
    import test_discovery as fixtures
    from app import discovery
    monkeypatch.setenv('VERIFICATION_PIPELINE_ENABLED','true')
    conn=db.connect(tmp_path/'dedupe.db')
    catalog=db.load_catalog_file(__import__('pathlib').Path(__file__).parents[1]/'data/catalog.json');db.seed(conn,catalog)
    request=discovery.DiscoveryRequest(capability='phone_answering')
    first=discovery.FinderResult.model_validate(fixtures.result(fixtures.candidate()))
    report=discovery.store(conn,catalog,request,first,date.today())
    assert len(report.added)==1
    second=discovery.FinderResult.model_validate(fixtures.result(fixtures.candidate(name='Never miss another call')))
    again=discovery.store(conn,catalog,request,second,date.today())
    assert not again.added and again.updated==report.added
    assert conn.execute("SELECT count(*) FROM tool WHERE origin='discovered'").fetchone()[0]==1
    conn.close()


@pytest.mark.parametrize('finish,content',[('length','{"feature":'),('stop','{"unexpected":"schema"}')])
def test_invalid_provider_extraction_is_settled_once_and_never_promoted(tmp_path,monkeypatch,catalog,finish,content):
    import httpx
    from types import SimpleNamespace
    from app.model_gateway import Ledger
    monkeypatch.setenv('VERIFICATION_PIPELINE_ENABLED','false')
    monkeypatch.setenv('DISCOVERY_OPENROUTER_KEY','test-only-not-a-provider-key')
    monkeypatch.setattr(auto_verification,'fetch_pages',lambda *args:{URL:'Our bookkeeping software serves small businesses. Contact sales for pricing.'})
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            return httpx.Response(200,request=httpx.Request('POST','https://example.com'),json={
                'usage':{'cost':.002},'choices':[{'finish_reason':finish,'message':{'content':content}}]})
    monkeypatch.setattr(auto_verification.httpx,'Client',Client)
    search=SimpleNamespace(ledger=Ledger(tmp_path/'spend.db'),max_requests=4,cap_usd=1)
    checked=auto_verification.review(source(),'bookkeeping',catalog,search)
    assert not checked.auto_review.eligible and checked.auto_review.checks['extraction_valid'] is False
    status=search.ledger.status()
    assert status['attempts']==1 and status['by_state']['settled']['usd']==.002 and not status['tripped']
