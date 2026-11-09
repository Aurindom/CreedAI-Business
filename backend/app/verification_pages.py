"""Shared public-source cache plus bounded, isolated browser fallback."""
import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit,urldefrag,urljoin
import httpx
from .domains import registrable_domain
from .discovery_worker.sources import Budget,SafeFetcher,HttpxTransport,system_resolver
from .discovery_worker.extract import _Parser, BLOCK_MARKERS
from .pricing_blocks import blocks_from_html,qualified_plan


class Pages(dict):
    def __init__(self):
        super().__init__();self.blocks=[];self.outcomes=[];self.billing={}


def cache_connection():
    path=os.environ.get('APP_DB_PATH')
    if not path:return None
    from . import db
    return db.connect(Path(path))


def cached(conn,url,now):
    if conn is None:return None
    row=conn.execute('SELECT doc FROM verification_page WHERE url=? AND expires>?',(url,now)).fetchone()
    return json.loads(row[0]) if row else None


def persist(conn,url,doc,mode,now):
    if conn is None:return
    raw=json.dumps(doc,sort_keys=True)
    with conn:
        conn.execute('INSERT INTO verification_page VALUES(?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET fetched=excluded.fetched,expires=excluded.expires,sha256=excluded.sha256,mode=excluded.mode,doc=excluded.doc',
            (url,now,now+86400,hashlib.sha256(raw.encode()).hexdigest(),mode,raw))


def render(url):
    endpoint=os.environ.get('RENDER_API_URL','').rstrip('/')
    token=os.environ.get('RENDER_API_KEY','')
    if not endpoint or len(token)<24:raise RuntimeError('renderer_unconfigured')
    with httpx.Client(timeout=32,trust_env=False,follow_redirects=False) as client:
        with client.stream('POST',endpoint+'/render',headers={'Authorization':'Bearer '+token},json={'url':url}) as response:
            response.raise_for_status();data=bytearray()
            for part in response.iter_bytes():
                data+=part
                if len(data)>900000:raise ValueError('render_payload_too_large')
    doc=json.loads(data)
    if (not isinstance(doc,dict) or doc.get('version')!=1 or not isinstance(doc.get('html'),str)
            or not isinstance(doc.get('url'),str) or len(doc['html'])>750000):raise ValueError('invalid_render_result')
    return doc


def fetch(tool,cancel=None,capability=None,catalog=None):
    result=Pages();start=time.monotonic();now=time.time();conn=cache_connection()
    budget=Budget(max_pages=3,time_budget_s=18,max_retries=0,cancel=cancel)
    fetcher=SafeFetcher(HttpxTransport(user_agent='MainStreetAI-Verification/2.0'),system_resolver,request_timeout_s=5)
    domain=registrable_domain(urlsplit(str(tool.url)).hostname or '')
    urls=[str(tool.url)]
    cap=tool.capability(capability) if capability else None
    for fact in (tool.plan_prices,tool.entry_monthly_usd,tool.entry_plan):
        if fact.source_url and str(fact.source_url) not in urls:urls.append(str(fact.source_url))
    for fact in ((cap.access,cap.included_from) if cap else ()):
        if fact.source_url and str(fact.source_url) not in urls:urls.append(str(fact.source_url))
    phrases=[capability.replace('_',' ')] if capability else []
    if catalog and capability:
        from .discovery_worker.contract import Snapshot
        phrases=Snapshot(catalog.model_dump(mode='json'),{}).phrases(capability)
    rendered=0
    try:
        index=0
        while index<min(len(urls),3) and time.monotonic()-start<65:
            if cancel is not None and cancel.is_set():raise RuntimeError('review_cancelled')
            url=urldefrag(urls[index])[0];index+=1
            if registrable_domain(urlsplit(url).hostname or '')!=domain:continue
            doc=cached(conn,url,now)
            if doc is None:
                try:
                    page=fetcher.fetch(url,budget);doc={'url':page.final_url,'html':page.text,'mode':'static'}
                except Exception as exc:
                    result.outcomes.append({'url':url,'code':'static_'+type(exc).__name__.lower()})
                    doc=None
                # Render every tool when its static document is empty or lacks
                # useful pricing structure; don't spend a browser on cache hits.
                parser=_Parser()
                if doc:parser.feed(doc['html']);parser.close()
                text=' '.join(' '.join(parser.text).split())
                useful=doc and any(qualified_plan(block,phrases) for block in blocks_from_html(doc['html'],doc['url']))
                if (not doc or len(text)<300 or not useful) and rendered<2 and os.environ.get('RENDER_API_URL'):
                    rendered+=1
                    try:
                        rendered_doc=render(url);rendered_doc['mode']='rendered'
                        if registrable_domain(urlsplit(rendered_doc['url']).hostname or '')==domain:
                            doc=rendered_doc
                    except Exception as exc:
                        result.outcomes.append({'url':url,'code':'render_'+type(exc).__name__.lower()})
                    if doc:doc['render_attempted']=True
                if doc and registrable_domain(urlsplit(doc['url']).hostname or '')==domain:
                    persist(conn,url,doc,doc['mode'],now)
            elif (rendered<2 and os.environ.get('RENDER_API_URL') and (
                    (doc.get('mode')=='static' and not doc.get('render_attempted')
                     and not any(qualified_plan(block,phrases) for block in blocks_from_html(doc['html'],doc['url'])))
                    or (doc.get('mode')=='rendered' and doc.get('render_policy')!=2 and doc.get('render_attempted_policy')!=2))):
                rendered+=1
                try:
                    rendered_doc=render(url)
                    if registrable_domain(urlsplit(rendered_doc['url']).hostname or '')==domain:
                        doc={**rendered_doc,'mode':'rendered'}
                except Exception as exc:
                    result.outcomes.append({'url':url,'code':'render_'+type(exc).__name__.lower()})
                doc['render_attempted']=True
                doc['render_attempted_policy']=2
                persist(conn,url,doc,doc['mode'],now)
            if not doc:continue
            if registrable_domain(urlsplit(doc['url']).hostname or '')!=domain:continue
            parser=_Parser();parser.feed(doc['html']);parser.close()
            text=' '.join(' '.join(parser.text).split())
            if len(text)<1500 and any(marker in text.lower() for marker in (*BLOCK_MARKERS,'enable javascript and cookies','performing security verification')):
                result.outcomes.append({'url':doc['url'],'code':'vendor_access_blocked'})
                continue
            if len(text)>=80:
                result[urldefrag(doc['url'])[0]]=text[:26000]
                blocks=blocks_from_html(doc['html'],doc['url'])
                result.blocks.extend(blocks)
                if blocks:result.billing[urldefrag(doc['url'])[0]]=blocks[0].get('billing_selection')
                result.outcomes.append({'url':doc['url'],'code':'read_'+doc.get('mode','static')})
            def link_priority(item):
                label=item[1].lower()
                if any(phrase in label for phrase in phrases):return 0
                return 1 if re.search(r'pricing|plans',label,re.I) else 2
            for href,label in sorted(parser.links,key=link_priority):
                link=urljoin(doc['url'],href)
                if (len(urls)<3 and (re.search(r'pricing|plans',label,re.I) or any(phrase in label.lower() for phrase in phrases))
                        and urlsplit(link).scheme=='https' and registrable_domain(urlsplit(link).hostname or '')==domain and link not in urls):urls.append(link)
        return result
    finally:
        if conn is not None:conn.close()
