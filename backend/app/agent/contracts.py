"""Two contracts meet here. Runtime events are what an agent runtime adapter must hand us; frames are the only
things the browser ever sees. Nothing passes from one side to the other without going through the turn logic."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TextDelta(_Strict):
    kind: Literal["text"] = "text"
    text: str


class ActionStarted(_Strict):
    kind: Literal["action_started"] = "action_started"
    call_id: str
    action: str


class ActionResult(_Strict):
    kind: Literal["action_result"] = "action_result"
    call_id: str
    result: Any = None


class RunEnded(_Strict):
    kind: Literal["run_end"] = "run_end"
    status: Literal["completed", "failed", "cancelled"]


RuntimeEvent = Union[TextDelta, ActionStarted, ActionResult, RunEnded]

ActionStatus = Literal["started", "succeeded", "failed", "unconfirmed"]
TurnStatus = Literal["completed", "failed", "cancelled", "timed_out", "interrupted", "rejected", "unavailable", "blocked"]
NoticeCode = Literal["busy", "unavailable", "timeout", "interrupted", "blocked", "run_failed", "run_cancelled"]


class ActionSpec(_Strict):
    name: str
    label: str
    failure_messages: dict[str, str] = Field(default_factory=dict)


class TextFrame(_Strict):
    type: Literal["text"] = "text"
    text: str


class ActionFrame(_Strict):
    type: Literal["action"] = "action"
    seq: int
    action: str | None
    label: str
    status: ActionStatus
    message: str


class NoticeFrame(_Strict):
    type: Literal["notice"] = "notice"
    code: NoticeCode
    message: str
    fallback: Literal["browse"] = "browse"


class DoneFrame(_Strict):
    type: Literal["done"] = "done"
    turn: TurnStatus
    succeeded: int = 0
    failed: int = 0
    unconfirmed: int = 0
    fallback: Literal["browse"] | None = None


Frame = Annotated[Union[TextFrame, ActionFrame, NoticeFrame, DoneFrame], Field(discriminator="type")]


def sse(frame: TextFrame | ActionFrame | NoticeFrame | DoneFrame) -> str:
    return "data: " + json.dumps(frame.model_dump(mode="json")) + "\n\n"
