"""Connects one Arkadio chat run to server-owned bindings, so every tool call is checked before it runs."""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import ValidationError

from .. import adoption
from ..access import account_owner
from ..auth import Principal
from ..comparison import AssignmentError
from ..schemas import BusinessProfile, Catalog, Selection
from . import bindings
from .completion import ExpectedAction, plan_request_id, saved_plan

logger = logging.getLogger(__name__)

DENIED_MESSAGES = {
    "forged_binding": "Account and business details come from the server. Call the action without them.",
    "not_allowed": "That action isn't available.",
    "sign_in_required": "Saving a plan needs a signed-in account. Keep browsing and comparing tools.",
    "session_ended": "This sign-in has ended, so private actions are closed.",
    "duplicate_call": "That action already ran for this call.",
    "unknown_run": "That action isn't available.",
}
PLAN_ERRORS = (ValidationError, KeyError, AssignmentError, adoption.PlanNotReady, adoption.PlanConflict, adoption.PlanLimit)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunGate:
    """Without a database the run is treated as public, so private actions fail closed rather than run unbound."""

    def __init__(self, conn: sqlite3.Connection | None, lock: threading.Lock | None, principal: Principal,
                 conversation_id: str, now: Callable[[], datetime] = _utc_now):
        self.conn = conn
        self.lock = lock or nullcontext()
        self.principal = principal
        self.now = now
        self.expected: list[ExpectedAction] = []
        if conn is None:
            self.binding: bindings.PublicBinding | bindings.RunBinding = bindings.PublicBinding(conversation_id)
            return
        with self.lock:
            self.binding = bindings.bind_run(conn, principal, conversation_id, now())

    @classmethod
    def resume(cls, conn: sqlite3.Connection, lock: threading.Lock | None, run_id: str,
               now: Callable[[], datetime] = _utc_now) -> "RunGate":
        """For a tool server that runs outside the chat route. Identity is reloaded from the row the route wrote,
        so the caller only ever proves which run it belongs to, never who it is."""
        gate = cls(None, None, Principal(), "")
        gate.conn, gate.lock, gate.now = conn, lock or nullcontext(), now
        with gate.lock:
            row = conn.execute("SELECT user_id, session_id, business_id, conversation_id FROM agent_run WHERE run_id=?",
                               (run_id,)).fetchone()
            if row is None:
                raise bindings.BindingDenied("unknown_run")
            user_id, session_id, business_id, conversation_id = row
            if not bindings.session_active(conn, user_id, session_id):
                raise bindings.BindingDenied("session_ended")
            owner, _ = account_owner(conn, user_id, now())
        gate.principal = Principal(user_id, session_id)
        gate.binding = bindings.RunBinding(run_id, user_id, session_id, owner, business_id, conversation_id)
        return gate

    def check(self, name: str, arguments: dict[str, Any]) -> str:
        return bindings.authorize(self.binding, name, arguments)

    def expect(self, action: str, arguments: dict[str, Any], call_id: str | None = None) -> ExpectedAction:
        """Registers a write the owner asked for before anything is dispatched. Only server code calls this, from a
        validated request, so the list of required steps never comes from what the model says it did."""
        if action not in bindings.PRIVATE_ACTIONS:
            raise bindings.BindingDenied("not_allowed")
        self.check(action, arguments)
        try:
            Selection.model_validate({**arguments, "profile": BusinessProfile().model_dump(mode="json")})
        except ValidationError as exc:
            raise bindings.BindingDenied("invalid_arguments") from exc
        operation = ExpectedAction(action, call_id, None, bindings.arguments_hash(arguments), self.binding.run_id)
        self.expected.append(operation)
        return operation

    def deliverable(self) -> bool:
        if self.conn is None:
            return True
        with self.lock:
            return bindings.may_deliver(self.conn, self.binding)

    def private_action(self, catalog: Catalog, call_id: str, name: str, arguments: dict[str, Any],
                       profile: BusinessProfile) -> dict[str, Any]:
        """The receipt is issued and redeemed in one server step. The model never sees it, and the outcome
        it is told comes from the stored result, so a failed save can't read back as a success."""
        if self.conn is None or name != "save_plan":
            return {"error": DENIED_MESSAGES["not_allowed"]}
        now = self.now()
        with self.lock:
            try:
                token = bindings.issue_receipt(self.conn, self.binding, call_id, name, arguments, now)
                redeemed = bindings.redeem(self.conn, token, self.principal, name, arguments, now)
            except bindings.BindingDenied as exc:
                return {"error": DENIED_MESSAGES.get(exc.code, DENIED_MESSAGES["not_allowed"])}
            saved = None
            try:
                selection = Selection.model_validate({**arguments, "profile": profile.model_dump(mode="json")})
                plan, _ = adoption.save_plan(self.conn, catalog, redeemed.owner_hash,
                                             plan_request_id(redeemed.run_id, call_id), selection, now)
                saved = plan.id
                result: Any = {"success": True}
            except PLAN_ERRORS as exc:
                result = {"success": False, "error": {"code": type(exc).__name__}}
            except Exception as exc:
                # The write may or may not have landed. Look for it instead of retrying or calling it a failure.
                logger.warning("private action raised after redemption: %s", type(exc).__name__)
                saved = self._reconcile(redeemed, call_id)
                result = {"success": True} if saved else {}
            try:
                status, _ = bindings.record_outcome(self.conn, token, result)
            except sqlite3.Error as exc:
                logger.warning("private action outcome not recorded: %s", type(exc).__name__)
                status = "succeeded" if saved else "unconfirmed"
        if status == "succeeded":
            return {"outcome": status, "saved": saved}
        if status == "unconfirmed":
            return {"outcome": status, "error": "We could not confirm whether the plan was saved. Do not try again."}
        return {"outcome": status, "error": "The plan was not saved."}

    def _reconcile(self, redeemed: bindings.RunBinding, call_id: str) -> str | None:
        try:
            return saved_plan(self.conn, redeemed.owner_hash, redeemed.run_id, call_id)
        except sqlite3.Error:
            return None
