"""Decides what a finished agent run actually did, from stored receipts and the effects they point to.

A completed run, a completed tool call or a confident sentence from the model proves nothing. Before any action
is reported as done, or the final answer is delivered, this module reads what the server itself recorded."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Mapping

from . import bindings

ReportStatus = Literal["succeeded", "failed", "unconfirmed", "not_executed"]
CODES = {"failed": "action_failed", "unconfirmed": "action_unconfirmed", "not_executed": "action_not_executed"}
PRIORITY = ("session_ended", "tool_unavailable", "private_tool_exposed", "untrusted_tool", "action_unconfirmed", "action_failed", "action_not_executed")
MESSAGES: dict[str, str] = {
    "succeeded": "Done.",
    "failed": "That step did not work. Nothing was changed for you.",
    "not_executed": "That step did not run. Nothing was changed for you.",
    "unconfirmed": "We could not confirm that step finished. Please check before relying on it.",
}


def plan_request_id(run_id: str, call_id: str) -> str:
    return "chat_" + hashlib.sha256(f"{run_id}:{call_id}".encode()).hexdigest()[:40]


def saved_plan(conn: sqlite3.Connection, owner_hash: str, run_id: str, call_id: str) -> str | None:
    row = conn.execute("SELECT id FROM adoption_plan WHERE owner_hash=? AND request_id=?",
                       (owner_hash, plan_request_id(run_id, call_id))).fetchone()
    return row[0] if row else None


EFFECTS: dict[str, Callable[[sqlite3.Connection, str, str, str], str | None]] = {"save_plan": saved_plan}


@dataclass(frozen=True)
class ExpectedAction:
    """Registered by the server before dispatch (RunGate.expect), never read from model output."""
    action: str
    call_id: str | None = None
    arguments: dict[str, Any] | None = None
    arguments_hash: str | None = None
    run_id: str | None = None

    def wanted_hash(self) -> str | None:
        if self.arguments_hash is not None:
            return self.arguments_hash
        return None if self.arguments is None else bindings.arguments_hash(self.arguments)


@dataclass(frozen=True)
class ToolSpec:
    server: str
    listed: str
    advertised: str
    arguments: frozenset[str]


PUBLIC_TOOLS: dict[str, ToolSpec] = {
    "get_tool_details": ToolSpec("marketplace", "get_tool_details", "mcp__marketplace__get_tool_details",
                                 frozenset({"tool_id", "operation"})),
}


@dataclass(frozen=True)
class ActionReport:
    action: str
    call_id: str | None
    status: ReportStatus
    expected: bool
    ref: str | None = None

    @property
    def code(self) -> str | None:
        return CODES.get(self.status)

    @property
    def message(self) -> str:
        return MESSAGES[self.status]


@dataclass(frozen=True)
class Completion:
    deliver: bool
    actions: tuple[ActionReport, ...] = ()
    extra_codes: tuple[str, ...] = field(default=())

    @property
    def code(self) -> str | None:
        codes = set(self.extra_codes) | {a.code for a in self.actions if a.code}
        if not self.deliver:
            codes.add("session_ended")
        return next((c for c in PRIORITY if c in codes), None)

    def succeeded(self, action: str) -> bool:
        return any(a.action == action and a.status == "succeeded" for a in self.actions)


def _schema_fields(schema: Any) -> frozenset[str] | None:
    if not isinstance(schema, Mapping):
        return None
    if isinstance(schema.get("function"), Mapping):
        schema = schema["function"].get("parameters") or {}
    properties = schema.get("properties")
    return frozenset(properties) if isinstance(properties, Mapping) else frozenset()


def check_tools(required: Iterable[str], available: Mapping[str, Any] | Iterable[str], layer: str = "advertised",
                tools: Mapping[str, ToolSpec] = PUBLIC_TOOLS,
                forbidden: Iterable[str] = bindings.PRIVATE_ACTIONS) -> str | None:
    """Tool identity is the exact identifier the trusted inventory names for this layer ("listed" for the MCP
    server's own list, "advertised" for what the runtime shows the model). A same-suffix tool from another
    server is untrusted, not a match. When a schema comes with the name, its argument fields must match too."""
    found = dict(available) if isinstance(available, Mapping) else {name: None for name in available}
    if any(name == f or name.endswith("_" + f) for f in forbidden for name in found):
        return "private_tool_exposed"
    trusted = {getattr(spec, layer): spec for spec in tools.values()}
    if any(name not in trusted for name in found):
        return "untrusted_tool"
    for key in required:
        spec = tools.get(key)
        name = getattr(spec, layer) if spec else None
        if name not in found:
            return "tool_unavailable"
        fields = _schema_fields(found[name])
        if fields is not None and fields != spec.arguments:
            return "tool_unavailable"
        schema = found[name]
        if layer == 'listed' and not isinstance(schema, Mapping):
            return "tool_unavailable"
        if isinstance(schema, Mapping):
            if isinstance(schema.get("function"), Mapping):
                schema = schema["function"].get("parameters") or {}
            mandatory = schema.get('required')
            if (schema.get("type") != "object" or not isinstance(mandatory, list)
                    or not all(isinstance(field, str) for field in mandatory) or set(mandatory) != spec.arguments
                    or any(not isinstance(schema["properties"][field], Mapping)
                           or schema["properties"][field].get("type") != "string" for field in spec.arguments)):
                return "tool_unavailable"
    return None


def _receipt_status(conn: sqlite3.Connection, binding: bindings.RunBinding, row: tuple) -> tuple[ReportStatus, str | None]:
    call_id, action, _, used_at, outcome = row
    if used_at is None:
        return "not_executed", None
    effect = EFFECTS.get(action)
    ref = effect(conn, binding.owner_hash, binding.run_id, call_id) if effect else None
    if ref is not None:
        return "succeeded", ref
    if outcome == "failed":
        return "failed", None
    return "unconfirmed", None


def finalize(conn: sqlite3.Connection | None, lock: threading.Lock | None,
             binding: bindings.PublicBinding | bindings.RunBinding,
             expected: Iterable[ExpectedAction] = (), extra_codes: Iterable[str] = ()) -> Completion:
    """Every receipt for the run is reported with its real state, expected or not. An expected action with no
    matching redeemed receipt did not run. A redeemed one whose effect can't be found is unconfirmed, never
    'nothing changed', because the write may have landed after the outcome was lost."""
    wanted = list(expected)
    if conn is None or not binding.private:
        reports = tuple(ActionReport(e.action, e.call_id, "not_executed", True) for e in wanted)
        return Completion(True, reports, tuple(extra_codes))
    with lock or nullcontext():
        deliver = bindings.session_active(conn, binding.user_id, binding.session_id)
        rows = conn.execute("SELECT call_id, action, arguments_hash, used_at, outcome FROM action_receipt"
                            " WHERE run_id=? ORDER BY rowid", (binding.run_id,)).fetchall()
        settled = [(row, *_receipt_status(conn, binding, row)) for row in rows]
    claimed: set[int] = set()
    reports: list[ActionReport] = []
    for want in wanted:
        wanted_hash = want.wanted_hash()
        bound = want.run_id is None or want.run_id == binding.run_id
        match = next((i for i, (row, _, _) in enumerate(settled) if bound and i not in claimed and row[1] == want.action
                      and (want.call_id is None or row[0] == want.call_id)
                      and (wanted_hash is None or row[2] == wanted_hash)), None)
        if match is None:
            reports.append(ActionReport(want.action, want.call_id, "not_executed", True))
            continue
        claimed.add(match)
        row, status, ref = settled[match]
        reports.append(ActionReport(row[1], row[0], status, True, ref))
    for i, (row, status, ref) in enumerate(settled):
        if i not in claimed:
            reports.append(ActionReport(row[1], row[0], status, False, ref))
    return Completion(deliver, tuple(reports), tuple(extra_codes))
