"""The bounded prior context a Hermes run gets. Each run starts a fresh Hermes session, so everything the model
may use from earlier turns is sent here, as data, inside one JSON value.

Stable constraints (trade, owned and excluded tools, budget, an unknown plan) are always kept. Old turns are
dropped oldest first until the whole thing fits. History is the owner's and Arkadio's earlier words, never
instructions or identity, so a turn that looks like an injection, carries personal data or repeats a guarded
secret is left out."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from .. import chat_guard
from ..penny_grounding import plan_already_unknown
from .guard import LeakGuard

MAX_CONTEXT_CHARS = 6000
MAX_TURNS = 8


def _plan_unknown(body: Any) -> bool:
    if plan_already_unknown(body):
        return True
    return any(item.role == "user" and plan_already_unknown(SimpleNamespace(message=item.text, history=[]))
               for item in body.history)


def _usable(text: str, guard: LeakGuard) -> bool:
    return not guard.leaks(text) and chat_guard.reason(text) is None


def build(body: Any, profile: Any, memory: Any, guard: LeakGuard) -> str:
    """profile is the page profile already merged with memory, so a trade or budget set on the page is kept."""
    constraints = {
        "trade": profile.trade,
        "owned_tools": [entry.tool_id for entry in profile.owned],
        "excluded_tools": list(memory.ruled_out),
        "budget_monthly_usd": profile.budget_monthly_usd,
        "plan_unknown": _plan_unknown(body),
        "active_task_ids": list(getattr(memory, 'active_task_ids', [])),
        "pending_question": getattr(memory, 'pending_question', None),
        "pending_task_ids": list(getattr(memory, 'pending_task_ids', [])),
    }
    turns = [{"role": item.role, "text": item.text} for item in body.history if _usable(item.text, guard)]
    turns = turns[-MAX_TURNS:]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    while True:
        serial = json.dumps({"constraints": constraints, "earlier_turns": turns}, ensure_ascii=False)
        if len(serial) <= MAX_CONTEXT_CHARS or not turns:
            return serial
        turns.pop(0)
        while turns and turns[0]["role"] != "user":
            turns.pop(0)
