from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .contract import CONTRACT_VERSION, Candidate, Evidence, PricePlan, Pricing, UsageCharge

STORE_SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidate (
    candidate_id TEXT PRIMARY KEY,
    vendor TEXT NOT NULL,
    vendor_domain TEXT NOT NULL,
    product TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 0,
    promoted_tool_id TEXT
);
CREATE TABLE IF NOT EXISTS observation (
    candidate_id TEXT NOT NULL REFERENCES candidate(candidate_id),
    url TEXT NOT NULL,
    role TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    checked TEXT NOT NULL,
    provenance TEXT NOT NULL,
    facts TEXT,
    failure TEXT,
    PRIMARY KEY (candidate_id, url)
);
CREATE TABLE IF NOT EXISTS run (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    request TEXT NOT NULL,
    status TEXT NOT NULL,
    provenance TEXT NOT NULL,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (ts REAL NOT NULL, pages INTEGER NOT NULL);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    """Experiment persistence. Separate from the application tool table, which db.seed clears on every start."""

    def __init__(self, path: Path, window_s: float = 3600.0, window_pages: int = 200):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.window_s = window_s
        self.window_pages = window_pages
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        with self._lock, self.conn:
            self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('contract_version', ?)", (CONTRACT_VERSION,))
            self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('store_schema_version', ?)", (str(STORE_SCHEMA_VERSION),))
        stored = self.conn.execute("SELECT value FROM meta WHERE key='contract_version'").fetchone()[0]
        if stored != CONTRACT_VERSION:
            raise RuntimeError(f"store holds contract {stored}, code is {CONTRACT_VERSION}")

    def close(self) -> None:
        self.conn.close()

    def try_acquire(self, n: int) -> bool:
        with self._lock, self.conn:
            cutoff = time.time() - self.window_s
            self.conn.execute("DELETE FROM ledger WHERE ts < ?", (cutoff,))
            used = self.conn.execute("SELECT COALESCE(SUM(pages), 0) FROM ledger").fetchone()[0]
            if used + n > self.window_pages:
                return False
            self.conn.execute("INSERT INTO ledger VALUES (?, ?)", (time.time(), n))
            return True

    def record_observation(
        self, candidate_id: str, vendor: str, vendor_domain: str, product: str, url: str, role: str,
        provenance: str, facts: dict | None, failure: str | None, checked: date,
    ) -> None:
        stamp = now_iso()
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO candidate (candidate_id, vendor, vendor_domain, product, first_seen, last_seen, seen_count)"
                " VALUES (?, ?, ?, ?, ?, ?, 0)",
                (candidate_id, vendor, vendor_domain, product, stamp, stamp),
            )
            if facts is not None:
                self.conn.execute("UPDATE candidate SET vendor=?, product=? WHERE candidate_id=?", (vendor, product, candidate_id))
            existing = self.conn.execute(
                "SELECT facts FROM observation WHERE candidate_id=? AND url=?", (candidate_id, url)
            ).fetchone()
            if facts is None and existing and existing[0]:
                self.conn.execute(
                    "UPDATE observation SET failure=?, observed_at=? WHERE candidate_id=? AND url=?",
                    (failure, stamp, candidate_id, url),
                )
                return
            self.conn.execute(
                "INSERT OR REPLACE INTO observation VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (candidate_id, url, role, stamp, checked.isoformat(), provenance,
                 json.dumps(facts) if facts is not None else None, failure),
            )

    def mark_seen(self, candidate_ids: set[str]) -> None:
        stamp = now_iso()
        with self._lock, self.conn:
            for cid in candidate_ids:
                self.conn.execute(
                    "UPDATE candidate SET seen_count = seen_count + 1, last_seen = ? WHERE candidate_id = ?", (stamp, cid)
                )

    def log_run(self, run_id: str, request: dict, status: str, provenance: str, summary: dict) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO run VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, now_iso(), json.dumps(request), status, provenance, json.dumps(summary)),
            )

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("candidate", "observation", "run")
            }

    def get(self, candidate_id: str) -> Candidate | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT candidate_id, vendor, vendor_domain, product, first_seen, last_seen, seen_count"
                " FROM candidate WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
            if row is None:
                return None
            obs = self.conn.execute(
                "SELECT url, role, checked, provenance, facts, failure FROM observation WHERE candidate_id = ? ORDER BY url",
                (candidate_id,),
            ).fetchall()
        return merge_candidate(row, obs)

    def list_ids(self, limit: int, after: str | None = None) -> list[str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT candidate_id FROM candidate WHERE candidate_id > ? ORDER BY candidate_id LIMIT ?",
                (after or "", limit),
            ).fetchall()
        return [r[0] for r in rows]


def merge_candidate(row: tuple, observations: list[tuple]) -> Candidate | None:
    cid, vendor, domain, product, first_seen, last_seen, seen_count = row
    caps: set[str] = set()
    facets: dict[str, set[str]] = {}
    trades: set[str] = set()
    not_offered: set[str] = set()
    hypotheses: dict[str, str] = {}
    evidence: list[Evidence] = []
    seen_ev: set[tuple] = set()
    plans: list[PricePlan] = []
    usage: list[UsageCharge] = []
    quote = False
    pricing_failures: list[str] = []
    provenances: set[str] = set()
    urls: list[str] = []
    product_url: str | None = None
    pricing_url: str | None = None
    unresolved: list[str] = []
    ok_obs = 0
    for url, role, checked, provenance, facts_json, failure in observations:
        urls.append(url)
        provenances.add(provenance)
        if role == "pricing":
            pricing_url = pricing_url or url
        if facts_json is None:
            if role == "pricing":
                pricing_failures.append(failure or "fetch_error")
            continue
        ok_obs += 1
        facts = json.loads(facts_json)
        if role == "product" and product_url is None:
            product_url = facts.get("canonical_url") or url
        if role == "product" and facts.get("pricing_link") and not pricing_url:
            pricing_url = facts["pricing_link"]
        caps.update(facts["capabilities"])
        for fid, values in facts["facets"].items():
            facets.setdefault(fid, set()).update(values)
        trades.update(facts["applicability_trades"])
        not_offered.update(facts.get("not_offered", []))
        hypotheses.update(facts.get("hypotheses", {}))
        quote = quote or facts["quote_only"]
        plans += [PricePlan(**p) for p in facts["plans"]]
        usage += [UsageCharge(**u) for u in facts["usage"]]
        if failure and role == "pricing":
            pricing_failures.append(failure)
        for ev in facts["evidence"]:
            key = (ev["field"], url, ev["excerpt"])
            if key not in seen_ev and len(evidence) < 60:
                seen_ev.add(key)
                evidence.append(Evidence(field=ev["field"], url=url, excerpt=ev["excerpt"][:240],
                                         checked=date.fromisoformat(checked), source_kind=provenance))
    if ok_obs == 0:
        return None

    verified = {f"capability.{c}" for c in caps} | {f"facet.{f}.{v}" for f, vs in facets.items() for v in vs} | {f"trade.{t}" for t in trades}
    conflicts = sorted(not_offered & verified)
    not_offered -= verified
    hypotheses = {k: v for k, v in hypotheses.items() if k not in verified}
    unresolved += [f"conflict.{k}" for k in conflicts]
    plans = list({(p.name, p.amount, p.currency, p.unit, p.billing): p for p in plans}.values())
    usage = list({(u.amount, u.currency, u.per): u for u in usage}.values())
    if any(p.currency is None for p in plans) or any(u.currency is None for u in usage):
        unresolved.append("pricing.currency")
    if plans:
        pricing = Pricing(state="fixed", plans=plans, usage_charges=usage)
        if quote:
            pricing.reason = "some tiers are quote-only"
        if any(p.billing == "unspecified" for p in plans):
            unresolved.append("pricing.billing_period")
    elif usage:
        pricing = Pricing(state="usage_based", usage_charges=usage)
    elif quote:
        pricing = Pricing(state="quote_only", reason="vendor does not publish a price")
        unresolved.append("pricing.amount")
    elif pricing_failures:
        pricing = Pricing(state="extraction_failed", reason=f"pricing page could not be read: {pricing_failures[0]}")
        unresolved.append("pricing")
    else:
        pricing = Pricing(state="unknown", reason="no pricing found on fetched pages")
        unresolved.append("pricing")
    if pricing.state == "fixed" and pricing_failures:
        pricing.reason = (pricing.reason + "; " if pricing.reason else "") + f"another pricing page failed: {pricing_failures[0]}"

    if len(trades) >= 3:
        applicability = "cross_industry"
    elif trades:
        applicability = "restricted"
    else:
        applicability = "unknown"
        unresolved.append("applicability")

    kind = provenances.pop() if len(provenances) == 1 else "mixed"
    return Candidate(
        candidate_id=cid, vendor=vendor, vendor_domain=domain, product=product,
        product_url=product_url or urls[0], pricing_url=pricing_url,
        capabilities=sorted(caps), facets={k: sorted(v) for k, v in sorted(facets.items())},
        not_offered=sorted(not_offered), hypotheses=dict(sorted(hypotheses.items())),
        applicability=applicability, applicability_trades=sorted(trades), pricing=pricing,
        evidence=evidence, source_urls=sorted(set(urls)), unresolved_fields=sorted(set(unresolved)),
        provenance=kind, first_seen=first_seen, last_seen=last_seen, seen_count=max(seen_count, 1),
    )
