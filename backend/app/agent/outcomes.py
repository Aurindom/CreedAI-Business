from __future__ import annotations

import json
from typing import Any, Literal

from .contracts import ActionSpec

Outcome = Literal["succeeded", "failed", "unconfirmed"]

MESSAGES: dict[str, str] = {
    "started": "Working on it.",
    "succeeded": "Done.",
    "failed": "That step did not work. Nothing was changed for you.",
    "unconfirmed": "We could not confirm that step finished. Please check before relying on it.",
    "not_allowed": "That step is not something this assistant is allowed to do.",
}


def action_outcome(result: Any) -> tuple[Outcome, str | None]:
    """Only an explicit success flag counts. A finished run, a plain string or a missing flag proves nothing."""
    if isinstance(result, (bytes, bytearray)):
        result = result.decode("utf-8", "replace")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            return "unconfirmed", None
    if not isinstance(result, dict):
        return "unconfirmed", None
    success, error = result.get("success"), result.get("error")
    if success is True and not error:
        return "succeeded", None
    if success is False or error:
        code = error.get("code") if isinstance(error, dict) else None
        return "failed", code if isinstance(code, str) else None
    return "unconfirmed", None


def outcome_message(status: str, spec: ActionSpec | None, code: str | None) -> str:
    if status == "failed" and spec and code and code in spec.failure_messages:
        return spec.failure_messages[code]
    return MESSAGES[status]
