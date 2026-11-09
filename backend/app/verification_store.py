"""Durable, leased catalog review jobs and scoped, auditable evidence overlays.

The source catalog stays intact. A review of one capability never overwrites
another capability or invents a plan hierarchy. All timestamps are UTC epochs.
"""
import hashlib
import json
import sqlite3
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS verification_job (
 tool_id TEXT NOT NULL, capability TEXT NOT NULL, input_hash TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'queued', due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 lease TEXT, lease_until REAL, code TEXT, updated REAL NOT NULL,
 PRIMARY KEY(tool_id,capability));
CREATE TABLE IF NOT EXISTS verification_review (
 id INTEGER PRIMARY KEY, tool_id TEXT NOT NULL, capability TEXT NOT NULL,
 input_hash TEXT NOT NULL, checked REAL NOT NULL, expires REAL NOT NULL,
 outcome TEXT NOT NULL, doc TEXT NOT NULL, reason TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS verification_scope ON verification_review(tool_id,capability,checked);
CREATE TABLE IF NOT EXISTS verification_overlay (
 tool_id TEXT NOT NULL, capability TEXT NOT NULL, input_hash TEXT NOT NULL,
 expires REAL NOT NULL, review_id INTEGER NOT NULL, doc TEXT NOT NULL,
 PRIMARY KEY(tool_id,capability));
CREATE TABLE IF NOT EXISTS verification_page (
 url TEXT PRIMARY KEY, fetched REAL NOT NULL, expires REAL NOT NULL, sha256 TEXT NOT NULL,
 mode TEXT NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verification_extraction (key TEXT PRIMARY KEY, created REAL NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verification_schedule (
 name TEXT PRIMARY KEY, due REAL NOT NULL, lease TEXT, lease_until REAL,
 runs INTEGER NOT NULL DEFAULT 0, code TEXT, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_query (
 key TEXT PRIMARY KEY, lease TEXT, lease_until REAL, expires REAL NOT NULL DEFAULT 0, doc TEXT);
"""


def ensure(conn):
    conn.executescript(SCHEMA)


def fingerprint(tool):
    doc = tool.model_dump(mode='json', exclude={'auto_review', 'reviews', 'verification_state'})
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_tools(conn):
    from .schemas import Tool
    return [Tool(**{**json.loads(doc),'origin':origin}) for doc,origin in conn.execute('SELECT doc,origin FROM tool ORDER BY id')]


def enqueue(conn, tools, now=None, force=False):
    now = time.time() if now is None else now
    count = 0
    with conn:
        for tool in tools:
            if tool.status == 'rejected':
                conn.execute("UPDATE verification_job SET state='retired',lease=NULL,lease_until=NULL,updated=? WHERE tool_id=?",(now,tool.id))
                continue
            digest = fingerprint(tool)
            active={cap.capability for cap in tool.capabilities}
            for (old_cap,) in conn.execute('SELECT capability FROM verification_job WHERE tool_id=?',(tool.id,)).fetchall():
                if old_cap not in active:
                    conn.execute("UPDATE verification_job SET state='retired',lease=NULL,lease_until=NULL,updated=? WHERE tool_id=? AND capability=?",(now,tool.id,old_cap))
            for cap in tool.capabilities:
                row = conn.execute('SELECT input_hash,state,lease_until FROM verification_job WHERE tool_id=? AND capability=?',
                                   (tool.id, cap.capability)).fetchone()
                if row is None:
                    conn.execute("INSERT INTO verification_job(tool_id,capability,input_hash,due,updated) VALUES(?,?,?,?,?)",
                                 (tool.id,cap.capability,digest,now,now))
                    count += 1
                elif row[0] != digest or row[1]=='retired' or force:
                    # A running old job loses its publication authority when its inputs change.
                    conn.execute("UPDATE verification_job SET input_hash=?,state='queued',due=?,lease=NULL,lease_until=NULL,code=NULL,attempts=0,updated=? WHERE tool_id=? AND capability=?",
                                 (digest,now,now,tool.id,cap.capability))
                    count += 1
    return count


def claim(conn, now=None, ttl=120):
    now = time.time() if now is None else now
    conn.execute('BEGIN IMMEDIATE')
    try:
        conn.execute("UPDATE verification_job SET state='retry',lease=NULL,lease_until=NULL,code='worker_interrupted',due=?,updated=? WHERE state='running' AND lease_until<=?", (now,now,now))
        # One leased review globally, including multiple accidentally started workers.
        if conn.execute("SELECT 1 FROM verification_job WHERE state='running' AND lease_until>?",(now,)).fetchone():
            conn.commit(); return None
        row=conn.execute("SELECT tool_id,capability,input_hash,attempts FROM verification_job WHERE state IN ('queued','retry','budget_paused','verified','partial','blocked') AND due<=? ORDER BY CASE state WHEN 'queued' THEN 0 WHEN 'retry' THEN 1 ELSE 2 END,due,tool_id,capability LIMIT 1",(now,)).fetchone()
        if row is None:
            conn.commit(); return None
        token=uuid.uuid4().hex
        conn.execute("UPDATE verification_job SET state='running',lease=?,lease_until=?,attempts=attempts+1,updated=? WHERE tool_id=? AND capability=?",(token,now+ttl,now,*row[:2]))
        conn.commit()
        return dict(tool_id=row[0],capability=row[1],input_hash=row[2],attempts=row[3]+1,lease=token)
    except BaseException:
        conn.rollback(); raise


def finish(conn, job, reviewed=None, outcome='partial', reason='incomplete_evidence', now=None, refresh_s=86400):
    now=time.time() if now is None else now
    if outcome not in ('verified','partial','blocked','budget_paused','retry'):
        raise ValueError('invalid_review_outcome')
    conn.execute('BEGIN IMMEDIATE')
    try:
        row=conn.execute("SELECT input_hash,lease,lease_until FROM verification_job WHERE tool_id=? AND capability=? AND state='running'",(job['tool_id'],job['capability'])).fetchone()
        if row is None or row[0]!=job['input_hash'] or row[1]!=job['lease'] or row[2]<=now:
            conn.rollback(); return False
        if reviewed is not None:
            raw=conn.execute('SELECT doc,origin FROM tool WHERE id=?',(job['tool_id'],)).fetchone()
            from .schemas import Tool
            if raw is None or fingerprint(Tool(**{**json.loads(raw[0]),'origin':raw[1]}))!=job['input_hash']:
                conn.execute("UPDATE verification_job SET state='queued',lease=NULL,lease_until=NULL,due=?,code='inputs_changed',updated=? WHERE tool_id=? AND capability=?",(now,now,job['tool_id'],job['capability']))
                conn.commit(); return False
            review=reviewed.auto_review
            if not review or review.capability!=job['capability'] or bool(review.eligible)!=(outcome=='verified'):
                raise ValueError('review_scope_mismatch')
            cursor=conn.execute('INSERT INTO verification_review(tool_id,capability,input_hash,checked,expires,outcome,doc,reason) VALUES(?,?,?,?,?,?,?,?)',
                (job['tool_id'],job['capability'],job['input_hash'],now,now+refresh_s,outcome,reviewed.model_dump_json(),reason))
            if outcome=='verified':
                conn.execute('INSERT INTO verification_overlay VALUES(?,?,?,?,?,?) ON CONFLICT(tool_id,capability) DO UPDATE SET input_hash=excluded.input_hash,expires=excluded.expires,review_id=excluded.review_id,doc=excluded.doc',
                    (job['tool_id'],job['capability'],job['input_hash'],now+refresh_s,cursor.lastrowid,reviewed.model_dump_json()))
            elif reason=='contradictory_evidence':
                conn.execute('DELETE FROM verification_overlay WHERE tool_id=? AND capability=?',(job['tool_id'],job['capability']))
        delay=refresh_s if outcome=='verified' else 3600 if outcome=='budget_paused' else min(86400,900*2**min(job['attempts']-1,6))
        conn.execute('UPDATE verification_job SET state=?,due=?,lease=NULL,lease_until=NULL,code=?,updated=? WHERE tool_id=? AND capability=?',
                     (outcome,now+delay,reason,now,job['tool_id'],job['capability']))
        conn.commit(); return True
    except BaseException:
        conn.rollback(); raise


def apply_overlays(conn, tools, now=None):
    from .schemas import Tool, Fact
    now=time.time() if now is None else now
    rows={}
    for tid,cap,digest,expires,doc in conn.execute('SELECT tool_id,capability,input_hash,expires,doc FROM verification_overlay ORDER BY capability'):
        rows.setdefault(tid,[]).append((cap,digest,expires,doc))
    result=[]
    latest={}
    for tid,cap,digest,doc in conn.execute('SELECT r.tool_id,r.capability,r.input_hash,r.doc FROM verification_review r JOIN (SELECT tool_id,capability,max(id) id FROM verification_review GROUP BY tool_id,capability) current ON r.id=current.id'):
        latest[(tid,cap)]=(digest,doc)
    for tool in tools:
        original=fingerprint(tool); merged=tool.model_copy(deep=True)
        for cap in tool.capabilities:
            last=latest.get((tool.id,cap.capability))
            if last and last[0]==original:
                checked=Tool.model_validate_json(last[1])
                if checked.auto_review:
                    merged.reviews[cap.capability]=checked.auto_review
        for capability,digest,expires,doc in rows.get(tool.id,[]):
            if digest!=original or tool.capability(capability) is None:
                continue
            checked=Tool.model_validate_json(doc)
            review=checked.auto_review
            if expires<=now and review:
                merged.reviews[capability]=review.model_copy(update={'eligible':False,'checks':{**review.checks,'fresh':False},'notes':['Source check is due. Confirm current plan details.']})
                merged.verification_state='refresh_due'
                continue
            if not review or not review.eligible or review.capability!=capability:
                continue
            cap=checked.capability(capability)
            if cap is None:
                continue
            cap=cap.model_copy(deep=True)
            cap.verified_plan_prices=cap.verified_plan_prices if cap.verified_plan_prices.known else checked.plan_prices
            cap.verified_billing=cap.verified_billing if cap.verified_billing.known else checked.entry_billing
            merged.capabilities=[cap if c.capability==capability else c for c in merged.capabilities]
            merged.reviews[capability]=review
            merged.status='verified'
            # Preserve the base plan hierarchy; newly observed tiers have no implied order.
            names=list(merged.plan_tiers.value) if merged.plan_tiers.known else []
            observed=list(checked.plan_tiers.value) if checked.plan_tiers.known else []
            if not merged.single_offering and any(str(n).casefold() not in {str(x).casefold() for x in names} for n in observed):
                names += [n for n in observed if str(n).casefold() not in {str(x).casefold() for x in names}]
                merged.plan_tiers=Fact(**{**checked.plan_tiers.model_dump(),'value':names})
                merged.plan_hierarchy_confirmed=False
            if checked.applicability!='unknown':
                merged.applicability=checked.applicability
                merged.applicability_source=checked.applicability_source
            merged.verification_state='source_checked'
        if merged.reviews and merged.verification_state is None:
            merged.verification_state='evidence_incomplete'
        result.append(Tool.model_validate(merged.model_dump()))
    return result


def status(conn):
    counts=dict(conn.execute('SELECT state,count(*) FROM verification_job GROUP BY state'))
    scheduled=conn.execute("SELECT due,runs,code FROM verification_schedule WHERE name='discovery'").fetchone()
    heartbeat=conn.execute("SELECT updated FROM verification_schedule WHERE name='worker'").fetchone()
    sources={tool.id:tool for tool in source_tools(conn) if tool.status!='rejected'}
    approved=sum(1 for tid,cap,digest,expires in conn.execute('SELECT tool_id,capability,input_hash,expires FROM verification_overlay')
                 if expires>time.time() and tid in sources and sources[tid].capability(cap) is not None and fingerprint(sources[tid])==digest)
    return {'scopes':sum(counts.values()),'states':counts,
            'tools':conn.execute('SELECT count(DISTINCT tool_id) FROM verification_job').fetchone()[0],
            'reviewed_attempts':conn.execute('SELECT count(*) FROM verification_review').fetchone()[0],
            'active_approved_scopes':approved,
            'worker_recent':bool(heartbeat and heartbeat[0]>time.time()-240),
            'scheduled_discovery':{'next_due':scheduled[0],'runs':scheduled[1],'last_outcome':scheduled[2]} if scheduled else None}


def schedule_claim(conn, name, interval=86400, now=None, ttl=120):
    now=time.time() if now is None else now
    conn.execute('BEGIN IMMEDIATE')
    try:
        conn.execute('INSERT OR IGNORE INTO verification_schedule(name,due,updated) VALUES(?,?,?)',(name,now,now))
        due,until=conn.execute('SELECT due,lease_until FROM verification_schedule WHERE name=?',(name,)).fetchone()
        if due>now or (until is not None and until>now):
            conn.commit(); return None
        lease=uuid.uuid4().hex
        conn.execute('UPDATE verification_schedule SET lease=?,lease_until=?,updated=? WHERE name=?',(lease,now+ttl,now,name))
        conn.commit(); return lease
    except BaseException:
        conn.rollback(); raise


def schedule_finish(conn,name,lease,code,interval=86400,now=None):
    now=time.time() if now is None else now
    with conn:
        return bool(conn.execute('UPDATE verification_schedule SET due=?,lease=NULL,lease_until=NULL,runs=runs+1,code=?,updated=? WHERE name=? AND lease=? AND lease_until>?',
            (now+interval,code,now,name,lease,now)).rowcount)


def query_claim(conn, request, now=None):
    now=time.time() if now is None else now
    key=hashlib.sha256(json.dumps({'capability':request.capability,'trade':request.trade,'facets':request.facets},sort_keys=True).encode()).hexdigest()
    conn.execute('BEGIN IMMEDIATE')
    try:
        conn.execute('INSERT OR IGNORE INTO discovery_query(key) VALUES(?)',(key,))
        until,expires,doc=conn.execute('SELECT lease_until,expires,doc FROM discovery_query WHERE key=?',(key,)).fetchone()
        if expires>now and doc:
            conn.commit();return {'state':'cached','key':key,'doc':json.loads(doc)}
        if until is not None and until>now:
            conn.commit();return {'state':'busy','key':key}
        lease=uuid.uuid4().hex
        conn.execute('UPDATE discovery_query SET lease=?,lease_until=? WHERE key=?',(lease,now+120,key))
        conn.commit();return {'state':'claimed','key':key,'lease':lease}
    except BaseException:
        conn.rollback();raise


def query_finish(conn,claim,report=None,now=None):
    now=time.time() if now is None else now
    ttl=3600 if report is not None and report.status in ('completed','partial') else 300
    with conn:
        return bool(conn.execute('UPDATE discovery_query SET lease=NULL,lease_until=NULL,expires=?,doc=? WHERE key=? AND lease=? AND lease_until>?',
            (now+ttl,report.model_dump_json() if report else None,claim['key'],claim['lease'],now)).rowcount)
