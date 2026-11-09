"""Public read operations the app registers before a Hermes run, and the exact result the MCP executor stored.

A completed Hermes event, or a tool body that says success, proves nothing. The app accepts a lookup only when
the executor recorded a terminal success for the operation this run registered, with the registered arguments,
and a result whose hash matches what the app's own catalog says now. The label in the tool argument is for
correlation only. It grants nothing and names no user, business or session."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..schemas import Catalog, Fact, Tool

ACTION = "get_tool_details"
MAX_OPERATIONS = 3
LABEL_PREFIX = "op_"
LABEL_LENGTH = len(LABEL_PREFIX) + 24

SCHEMA = """
CREATE TABLE IF NOT EXISTS public_operation (
    label TEXT PRIMARY KEY,
    run_key TEXT NOT NULL,
    action TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    arguments_hash TEXT NOT NULL,
    expected_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'running', 'succeeded', 'failed')),
    result_hash TEXT,
    code TEXT,
    started_at TEXT,
    finished_at TEXT
);
"""


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if 'expected_doc' not in {row[1] for row in conn.execute('PRAGMA table_info(public_operation)')}:
        conn.execute('ALTER TABLE public_operation ADD COLUMN expected_doc TEXT')


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fact(fact: Fact | None) -> dict[str, Any]:
    if fact is None or fact.status == "unknown":
        return {"status": "unknown"}
    found: dict[str, Any] = {"status": fact.status, "value": fact.value}
    if fact.source_url:
        found["source_url"] = str(fact.source_url)
    if fact.checked:
        found["checked"] = str(fact.checked)
    if fact.note:
        found["note"] = fact.note
    return found


def public_details(tool: Tool) -> dict[str, Any]:
    """The one public shape of a tool, used by the direct runtime, the MCP executor and the app's check."""
    return {
        "id": tool.id,
        "name": tool.name,
        "review_status": tool.status,
        "summary": tool.summary,
        "entry_monthly_usd": _fact(tool.entry_monthly_usd),
        "entry_plan": _fact(tool.entry_plan),
        "setup_effort": _fact(tool.setup_effort),
        "privacy": _fact(tool.privacy),
        "support": _fact(tool.support_stability),
        "connects_to": _fact(tool.connects_to),
        "capabilities": [c.capability for c in tool.capabilities],
        "capability_evidence": {c.capability:{
            'access':_fact(c.access), 'included_from':_fact(c.included_from),
            'verified_plan_prices':_fact(c.verified_plan_prices),
            'verified_billing':_fact(c.verified_billing),
            'source_checked':bool(tool.reviews.get(c.capability) and tool.reviews[c.capability].eligible),
        } for c in tool.capabilities},
    }


def result_hash(details: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(details, sort_keys=True, default=str).encode()).hexdigest()


def arguments_hash(tool_id: str) -> str:
    return hashlib.sha256(json.dumps({"tool_id": tool_id}, sort_keys=True).encode()).hexdigest()


def visible(catalog: Catalog, tool_id: str) -> Tool | None:
    found = next((tool for tool in catalog.tools if tool.id == tool_id), None)
    return None if found is None or found.status == "rejected" else found


def required_tool_ids(package: Any) -> list[str]:
    """Reads are required for every tool the answer may talk about: the winners and any tool behind a required
    claim. A clarification names no tool, so it needs no lookup. More than MAX_OPERATIONS is refused by the
    caller rather than silently trimmed."""
    claims = {claim.id: claim for claim in package.claims}
    found: list[str] = []
    for tool_id in package.winner_tool_ids:
        if tool_id not in found:
            found.append(tool_id)
    for claim_id in package.required_claim_ids:
        claim = claims.get(claim_id)
        if claim is not None and claim.tool_id and claim.tool_id not in found:
            found.append(claim.tool_id)
    return found


@dataclass(frozen=True)
class Operation:
    label: str
    tool_id: str
    expected_hash: str


@dataclass(frozen=True)
class Verdict:
    ok: bool
    code: str | None = None


def register(conn: sqlite3.Connection, lock: threading.Lock | None, catalog: Catalog, tool_ids: list[str],
             ttl_seconds: float) -> tuple[str, list[Operation]]:
    """Writes one pending row per required read. The run key stays in the app and is never sent to the model."""
    if len(tool_ids) > MAX_OPERATIONS:
        raise ValueError("too_many_operations")
    run_key = secrets.token_hex(16)
    expires = (_now() + timedelta(seconds=ttl_seconds)).isoformat()
    operations: list[Operation] = []
    for tool_id in tool_ids:
        tool = visible(catalog, tool_id)
        if tool is None:
            raise ValueError("unknown_tool")
        operations.append(Operation(LABEL_PREFIX + secrets.token_hex(12), tool_id, result_hash(public_details(tool))))
    with lock or nullcontext():
        ensure(conn)
        with conn:
            conn.executemany(
                "INSERT INTO public_operation (label, run_key, action, tool_id, arguments_hash, expected_hash, "
                "expires_at, state, expected_doc) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                [(op.label, run_key, ACTION, op.tool_id, arguments_hash(op.tool_id), op.expected_hash, expires,
                  json.dumps(public_details(catalog.tool(op.tool_id)),sort_keys=True))
                 for op in operations])
    return run_key, operations


def execute(conn: sqlite3.Connection, catalog: Catalog, label: Any, tool_id: Any) -> dict[str, Any]:
    """Runs inside the MCP executor. The pending to running step is one write, so a label can be used once and
    a second caller cannot race it. A row left 'running' by a crash stays unproven forever."""
    if not isinstance(label, str) or len(label) != LABEL_LENGTH or not label.startswith(LABEL_PREFIX):
        return {"success": False, "error": {"code": "unknown_operation"}}
    if not isinstance(tool_id, str) or not tool_id or len(tool_id) > 120:
        return {"success": False, "error": {"code": "invalid_arguments"}}
    now = _now().isoformat()
    ensure(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT action, arguments_hash, expires_at, state, expected_doc, expected_hash FROM public_operation WHERE label = ?",
                           (label,)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return {"success": False, "error": {"code": "unknown_operation"}}
        action, args_hash, expires_at, state, expected_doc, expected_hash = row
        if state != "pending" or action != ACTION:
            conn.execute("ROLLBACK")
            return {"success": False, "error": {"code": "operation_used"}}
        if expires_at <= now:
            conn.execute("UPDATE public_operation SET state = 'failed', code = 'expired', finished_at = ? "
                         "WHERE label = ?", (now, label))
            conn.execute("COMMIT")
            return {"success": False, "error": {"code": "expired"}}
        if args_hash != arguments_hash(tool_id):
            conn.execute("UPDATE public_operation SET state = 'failed', code = 'arguments_mismatch', "
                         "finished_at = ? WHERE label = ?", (now, label))
            conn.execute("COMMIT")
            return {"success": False, "error": {"code": "arguments_mismatch"}}
        conn.execute("UPDATE public_operation SET state = 'running', started_at = ? WHERE label = ?", (now, label))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    tool = visible(catalog, tool_id)
    if tool is None:
        _finish(conn, label, "failed", None, "unknown_tool")
        return {"success": False, "error": {"code": "unknown_tool"}}
    details = json.loads(expected_doc) if expected_doc else public_details(tool)
    if (not isinstance(details,dict) or details.get('id')!=tool_id
            or result_hash(details)!=expected_hash):
        _finish(conn,label,'failed',None,'snapshot_mismatch')
        return {'success':False,'error':{'code':'snapshot_mismatch'}}
    _finish(conn, label, "succeeded", result_hash(details), None)
    return {"success": True, "tool": details}


def _finish(conn: sqlite3.Connection, label: str, state: str, digest: str | None, code: str | None) -> None:
    with conn:
        conn.execute("UPDATE public_operation SET state = ?, result_hash = ?, code = ?, finished_at = ? "
                     "WHERE label = ? AND state = 'running'", (state, digest, code, _now().isoformat(), label))


def verify(conn: sqlite3.Connection, lock: threading.Lock | None, catalog: Catalog, run_key: str,
           operations: list[Operation]) -> Verdict:
    """Checks every registered read against the stored record and against the catalog as it is now, so a result
    computed from older data cannot back a claim about newer data."""
    if not operations:
        return Verdict(True)
    with lock or nullcontext():
        rows = {row[0]: row[1:] for row in conn.execute(
            "SELECT label, run_key, tool_id, state, result_hash, code, expires_at, finished_at FROM public_operation "
            f"WHERE label IN ({','.join('?' * len(operations))})", [op.label for op in operations])}
    for op in operations:
        row = rows.get(op.label)
        if row is None:
            return Verdict(False, "tool_missing")
        owner, tool_id, state, digest, code, expires, finished = row
        if owner != run_key or tool_id != op.tool_id:
            return Verdict(False, "tool_missing")
        if state in ("pending", "running"):
            return Verdict(False, "tool_missing" if state == "pending" else "tool_unconfirmed")
        if state != "succeeded":
            return Verdict(False, "tool_unavailable")
        # TTL bounds execution completion; later delivery still checks the current catalog.
        if finished is None or finished > expires:
            return Verdict(False, "tool_unavailable")
        tool = visible(catalog, op.tool_id)
        current = result_hash(public_details(tool)) if tool is not None else None
        if digest is None or digest != op.expected_hash or digest != current:
            return Verdict(False, "tool_result_mismatch")
    return Verdict(True)
