from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from statistics import median
from typing import AsyncIterator, Awaitable, Callable, Mapping

from ..capacity import Capacity
from .contracts import (ActionFrame, ActionResult, ActionSpec, ActionStarted, DoneFrame, NoticeCode, NoticeFrame,
                        RunEnded, RuntimeEvent, TextDelta, TextFrame, TurnStatus)
from .bindings import PRIVATE_ACTIONS
from .completion import MESSAGES as REPORT_MESSAGES, ActionReport, Completion
from .guard import LeakGuard
from .outcomes import MESSAGES, action_outcome, outcome_message

AppFrame = TextFrame | ActionFrame | NoticeFrame | DoneFrame

NOTICES: dict[NoticeCode, str] = {
    "busy": "The assistant is helping other owners right now. You can keep browsing and comparing tools, or try again in a minute.",
    "unavailable": "The assistant is not reachable right now. Browsing and comparing tools still work.",
    "timeout": "That took too long, so we stopped waiting. Browsing and comparing tools still work.",
    "interrupted": "The assistant stopped partway through. Browsing and comparing tools still work.",
    "blocked": "We stopped that reply because it contained something it should not. Browsing and comparing tools still work.",
    "run_failed": "The assistant could not finish that request. Browsing and comparing tools still work.",
    "run_cancelled": "That request was cancelled. Browsing and comparing tools still work.",
    "session_ended": "This sign-in has ended, so the answer was not shown. Sign in again to continue.",
}


class RuntimeUnavailable(Exception):
    """Raised by an adapter when the runtime could not be reached. Its message is never shown to the owner."""


@dataclass(frozen=True)
class Runtime:
    start: Callable[[], Awaitable[AsyncIterator[RuntimeEvent]]]
    duplicate_safe_start: bool = False


@dataclass(frozen=True)
class TurnPolicy:
    total_s: float = 90.0
    idle_s: float = 30.0
    start_attempts: int = 2
    retry_wait_s: float = 0.5
    cleanup_s: float = 5.0

    def __post_init__(self) -> None:
        if min(self.total_s, self.idle_s, self.cleanup_s) <= 0 or self.start_attempts < 1 or self.retry_wait_s < 0:
            raise ValueError("turn limits must be positive")


@dataclass(frozen=True)
class TurnRecord:
    status: TurnStatus
    first_text_s: float | None
    complete_s: float
    succeeded: int
    failed: int
    unconfirmed: int
    cleanup_confirmed: bool


@dataclass
class Stats:
    records: list[TurnRecord] = field(default_factory=list)

    def add(self, record: TurnRecord) -> None:
        self.records.append(record)

    def summary(self) -> dict:
        done = [r for r in self.records if r.status == "completed"]
        firsts = [r.first_text_s for r in done if r.first_text_s is not None]
        return {
            "turns": len(self.records),
            "completed": len(done),
            "rejected": sum(r.status == "rejected" for r in self.records),
            "not_completed": sum(r.status not in ("completed", "rejected") for r in self.records),
            "median_first_text_s": round(median(firsts), 3) if firsts else None,
            "median_complete_s": round(median(r.complete_s for r in done), 3) if done else None,
        }


async def call_with_retry(call: Callable[[], Awaitable], *, attempts: int, write: bool, duplicate_safe: bool,
                          wait_s: float):
    """A write is tried once unless the runtime promises duplicate protection, because a lost reply may hide a success."""
    tries = attempts if (not write or duplicate_safe) else 1
    for attempt in range(1, tries + 1):
        try:
            return await call()
        except RuntimeUnavailable:
            if attempt == tries:
                raise
            await asyncio.sleep(wait_s)


class _Turn:
    def __init__(self, actions: Mapping[str, ActionSpec], guard: LeakGuard,
                 settle: Callable[[], Completion] | None = None) -> None:
        self.actions = actions
        self.guard = guard
        self.settle = settle
        self.held: list[str] = []
        self.calls: dict[str, tuple[int, ActionSpec | None, str]] = {}
        self.counts = {"succeeded": 0, "failed": 0, "unconfirmed": 0}

    def _action(self, seq: int, spec: ActionSpec | None, status: str, code: str | None = None) -> ActionFrame:
        message = MESSAGES["not_allowed"] if spec is None and status == "failed" else outcome_message(status, spec, code)
        return ActionFrame(seq=seq, action=spec.name if spec else None, label=spec.label if spec else "Unlisted step",
                           status=status, message=message)

    def _settle(self, call_id: str, status: str, code: str | None = None) -> ActionFrame:
        seq, spec, _ = self.calls[call_id]
        self.calls[call_id] = (seq, spec, status)
        self.counts[status] += 1
        return self._action(seq, spec, status, code)

    def handle(self, event: RuntimeEvent) -> list[AppFrame]:
        if isinstance(event, TextDelta):
            text = self.guard.feed(event.text)
            if text and self.settle:
                self.held.append(text)
                return []
            return [TextFrame(text=text)] if text else []
        if isinstance(event, ActionStarted):
            if event.call_id in self.calls:
                return []
            spec = self.actions.get(event.action)
            self.calls[event.call_id] = (len(self.calls) + 1, spec, "started")
            if spec is None:
                return [self._settle(event.call_id, "failed")]
            return [self._action(len(self.calls), spec, "started")]
        if isinstance(event, ActionResult):
            known = self.calls.get(event.call_id)
            if known is None or known[2] != "started":
                return []
            if self.settle and known[1] and known[1].name in PRIVATE_ACTIONS:
                return []
            status, code = action_outcome(event.result)
            return [self._settle(event.call_id, status, code)]
        return []

    def _private_calls(self) -> list[tuple[str, ActionSpec]]:
        return [(call_id, spec) for call_id, (_, spec, status) in self.calls.items()
                if status == "started" and spec and spec.name in PRIVATE_ACTIONS]

    def _report(self, call_id: str | None, spec: ActionSpec | None, report: ActionReport) -> ActionFrame:
        status = "failed" if report.status == "not_executed" else report.status
        if call_id is None:
            call_id = f"report-{len(self.calls) + 1}"
            self.calls[call_id] = (len(self.calls) + 1, spec, "started")
        frame = self._settle(call_id, status)
        return frame.model_copy(update={"message": REPORT_MESSAGES[report.status]})

    def _settled(self) -> tuple[Completion | None, list[AppFrame]]:
        """Private calls are settled only from what the server stored. If that check itself fails, they stay
        unconfirmed and the answer is held back, because nothing trustworthy says what happened."""
        try:
            completion = self.settle()
        except Exception:
            return None, []
        reports = list(completion.actions)
        frames: list[AppFrame] = []
        for call_id, spec in self._private_calls():
            match = next((r for r in reports if r.call_id == call_id), None) or next((r for r in reports if r.action == spec.name), None)
            if match is None:
                continue
            reports.remove(match)
            frames.append(self._report(call_id, spec, match))
        for report in reports:
            spec = self.actions.get(report.action) or ActionSpec(name=report.action, label="Account step")
            frames.append(self._report(None, spec, report))
        return completion, frames

    def finish(self, turn: TurnStatus, notice: NoticeCode | None) -> list[AppFrame]:
        frames: list[AppFrame] = []
        tail = self.guard.flush()
        completion, code = None, None
        if self.settle:
            completion, reported = self._settled()
            text = "".join(self.held) + tail
            if completion is not None and completion.deliver and text:
                frames.append(TextFrame(text=text))
            frames += reported
            code = completion.code if completion else "action_unconfirmed"
        elif tail:
            frames.append(TextFrame(text=tail))
        for call_id, (_, _, status) in list(self.calls.items()):
            if status == "started":
                frames.append(self._settle(call_id, "unconfirmed"))
        if notice:
            frames.append(NoticeFrame(code=notice, message=NOTICES[notice]))
        if completion is not None and not completion.deliver:
            frames.append(NoticeFrame(code="session_ended", message=NOTICES["session_ended"]))
        frames.append(DoneFrame(turn=turn, fallback=None if turn == "completed" else "browse", code=code, **self.counts))
        return frames


def _visible(frame: AppFrame) -> list[str]:
    return [v for v in frame.model_dump().values() if isinstance(v, str)]


async def _close(stream, cleanup_s: float) -> bool:
    closer = getattr(stream, "aclose", None)
    if closer is None:
        return True
    try:
        await asyncio.wait_for(closer(), cleanup_s)
        return True
    except Exception:
        return False


async def run_turn(runtime: Runtime, actions: Mapping[str, ActionSpec], guard: LeakGuard, capacity: Capacity,
                   policy: TurnPolicy = TurnPolicy(), on_finish: Callable[[TurnRecord], None] | None = None,
                   settle: Callable[[], Completion] | None = None) -> AsyncIterator[AppFrame]:
    """One owner turn. Action outcomes and the turn's own status are reported separately, every frame passes the
    leak guard, and any stop other than a completed run hands the owner back to browsing. With settle, the
    answer is held until the server's own records say what the private steps did, and only then released."""
    began = time.monotonic()
    first_text: float | None = None
    turn = _Turn(actions, guard, settle)
    claim = capacity.try_claim()
    if claim is None:
        for frame in turn.finish("rejected", "busy"):
            yield frame
        if on_finish:
            on_finish(TurnRecord("rejected", None, time.monotonic() - began, 0, 0, 0, True))
        return

    stream = None
    status: TurnStatus = "interrupted"
    cleaned = True
    loop = asyncio.get_running_loop()
    deadline = loop.time() + policy.total_s
    try:
        try:
            stream = await asyncio.wait_for(
                call_with_retry(runtime.start, attempts=policy.start_attempts, write=True,
                                duplicate_safe=runtime.duplicate_safe_start, wait_s=policy.retry_wait_s),
                policy.total_s)
        except (RuntimeUnavailable, asyncio.TimeoutError):
            status, ending = "unavailable", turn.finish("unavailable", "unavailable")
        else:
            events = stream.__aiter__()
            ending = None
            while ending is None:
                wait = min(policy.idle_s, deadline - loop.time())
                try:
                    if wait <= 0:
                        raise asyncio.TimeoutError
                    event = await asyncio.wait_for(events.__anext__(), wait)
                except asyncio.TimeoutError:
                    status, ending = "timed_out", turn.finish("timed_out", "timeout")
                    break
                except Exception:
                    status, ending = "interrupted", turn.finish("interrupted", "interrupted")
                    break
                if isinstance(event, RunEnded):
                    status = {"completed": "completed", "failed": "failed", "cancelled": "cancelled"}[event.status]
                    notice = {"completed": None, "failed": "run_failed", "cancelled": "run_cancelled"}[event.status]
                    ending = turn.finish(status, notice)
                    break
                for frame in turn.handle(event):
                    if not isinstance(frame, TextFrame) and guard.leaks(*_visible(frame)):
                        guard.tripped = True
                    if guard.tripped:
                        break
                    if isinstance(frame, TextFrame) and first_text is None:
                        first_text = time.monotonic() - began
                    yield frame
                if guard.tripped:
                    status, ending = "blocked", _blocked(turn)
        for frame in ending:
            if guard.leaks(*_visible(frame)):
                continue
            if isinstance(frame, TextFrame) and first_text is None:
                first_text = time.monotonic() - began
            yield frame
    finally:
        claim.stopping()
        if stream is not None:
            cleaned = await _close(stream, policy.cleanup_s)
        claim.release()
        if on_finish:
            on_finish(TurnRecord(status, first_text, time.monotonic() - began, turn.counts["succeeded"],
                                 turn.counts["failed"], turn.counts["unconfirmed"], cleaned))


def _blocked(turn: _Turn) -> list[AppFrame]:
    return [f for f in turn.finish("blocked", "blocked") if not isinstance(f, TextFrame)]
