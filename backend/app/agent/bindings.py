"""Server-owned identity for agent runs, and single-use receipts for private actions.

Authority comes only from a verified Principal and rows this server wrote. Owner, business or
user ids that arrive in model arguments or frontend fields are treated as forgery, never as input."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..access import account_owner
from ..auth import Principal
from .outcomes import Outcome, action_outcome

RECEIPT_SECONDS = 120

PUBLIC_ACTIONS = frozenset({"recommend_tools", "compare_tools", "get_tool_details", "update_memory", "ask_owner", "submit_answer"})
PRIVATE_ACTIONS = frozenset({"save_plan"})
RESERVED_ARGUMENTS = frozenset({"user_id", "owner", "owner_hash", "owner_id", "business_id", "session_id", "account", "account_id", "run_id", "receipt"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_run (
    run_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    business_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_receipt (
    receipt_hash TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_run(run_id),
    call_id TEXT NOT NULL,
    action TEXT NOT NULL,
    arguments_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    outcome TEXT,
    UNIQUE (run_id, call_id)
);
"""


class BindingDenied(Exception):
    """Carries a stable code for the caller. The message never repeats a receipt or identifier."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PublicBinding:
    conversation_id: str

    @property
    def private(self) -> bool:
        return False


@dataclass(frozen=True)
class RunBinding:
    run_id: str
    user_id: str
    session_id: str
    owner_hash: str
    business_id: str
    conversation_id: str

    @property
    def private(self) -> bool:
        return True


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def arguments_hash(arguments: dict[str, Any]) -> str:
    return _hash(json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str))


def session_active(conn: sqlite3.Connection, user_id: str, session_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM revoked_auth_session WHERE session_id=? AND user_id=?", (session_id, user_id)).fetchone()
    return row is None


def _conversation_open(conn: sqlite3.Connection, user_id: str, conversation_id: str, now: datetime) -> bool:
    row = conn.execute("SELECT recover_until FROM chat_conversation WHERE user_id=? AND conversation_id=?", (user_id, conversation_id)).fetchone()
    return row is None or row[0] is None or datetime.fromisoformat(row[0]) > now


def bind_run(conn: sqlite3.Connection, principal: Principal, conversation_id: str, now: datetime) -> PublicBinding | RunBinding:
    if not principal.authenticated:
        return PublicBinding(conversation_id)
    if not principal.session_id or not session_active(conn, principal.user_id, principal.session_id):
        raise BindingDenied("session_ended")
    if not _conversation_open(conn, principal.user_id, conversation_id, now):
        raise BindingDenied("conversation_closed")
    owner, business = account_owner(conn, principal.user_id, now)
    run_id = str(uuid.uuid4())
    with conn:
        conn.execute("INSERT INTO agent_run VALUES(?,?,?,?,?,?)",
                     (run_id, principal.user_id, principal.session_id, business, conversation_id, now.isoformat()))
    return RunBinding(run_id, principal.user_id, principal.session_id, owner, business, conversation_id)


def authorize(binding: PublicBinding | RunBinding, action: str, arguments: dict[str, Any]) -> str:
    if RESERVED_ARGUMENTS & set(arguments):
        raise BindingDenied("forged_binding")
    if action in PUBLIC_ACTIONS:
        return "public"
    if action not in PRIVATE_ACTIONS:
        raise BindingDenied("not_allowed")
    if not binding.private:
        raise BindingDenied("sign_in_required")
    return "private"


def issue_receipt(conn: sqlite3.Connection, binding: PublicBinding | RunBinding, call_id: str, action: str,
                  arguments: dict[str, Any], now: datetime, seconds: int = RECEIPT_SECONDS) -> str:
    if authorize(binding, action, arguments) != "private":
        raise BindingDenied("not_private")
    if not session_active(conn, binding.user_id, binding.session_id):
        raise BindingDenied("session_ended")
    token = secrets.token_urlsafe(32)
    try:
        with conn:
            conn.execute("INSERT INTO action_receipt(receipt_hash, run_id, call_id, action, arguments_hash, expires_at) VALUES(?,?,?,?,?,?)",
                         (_hash(token), binding.run_id, call_id, action, arguments_hash(arguments), (now + timedelta(seconds=seconds)).isoformat()))
    except sqlite3.IntegrityError:
        raise BindingDenied("duplicate_call") from None
    return token


def redeem(conn: sqlite3.Connection, token: str, principal: Principal, action: str, arguments: dict[str, Any], now: datetime) -> RunBinding:
    if not principal.authenticated:
        raise BindingDenied("sign_in_required")
    if RESERVED_ARGUMENTS & set(arguments):
        raise BindingDenied("forged_binding")
    row = conn.execute(
        "SELECT r.receipt_hash, r.action, r.arguments_hash, r.expires_at, r.used_at, a.run_id, a.user_id, a.session_id, a.business_id, a.conversation_id"
        " FROM action_receipt r JOIN agent_run a ON a.run_id = r.run_id WHERE r.receipt_hash=?", (_hash(token or ""),)).fetchone()
    if row is None:
        raise BindingDenied("unknown_receipt")
    receipt, bound_action, bound_arguments, expires, used, run_id, user_id, session_id, business, conversation = row
    if user_id != principal.user_id:
        raise BindingDenied("wrong_account")
    if session_id != principal.session_id or not session_active(conn, user_id, session_id):
        raise BindingDenied("session_ended")
    if bound_action != action or bound_arguments != arguments_hash(arguments):
        raise BindingDenied("action_mismatch")
    if used is not None:
        raise BindingDenied("replayed")
    if datetime.fromisoformat(expires) <= now:
        raise BindingDenied("expired")
    with conn:
        claimed = conn.execute("UPDATE action_receipt SET used_at=? WHERE receipt_hash=? AND used_at IS NULL", (now.isoformat(), receipt)).rowcount
    if claimed != 1:
        raise BindingDenied("replayed")
    owner, _ = account_owner(conn, user_id, now)
    return RunBinding(run_id, user_id, session_id, owner, business, conversation)


def record_outcome(conn: sqlite3.Connection, token: str, result: Any) -> tuple[Outcome, str | None]:
    status, code = action_outcome(result)
    with conn:
        conn.execute("UPDATE action_receipt SET outcome=? WHERE receipt_hash=? AND used_at IS NOT NULL", (status, _hash(token)))
    return status, code


def may_deliver(conn: sqlite3.Connection, binding: PublicBinding | RunBinding) -> bool:
    if not binding.private:
        return True
    return session_active(conn, binding.user_id, binding.session_id)
