import asyncio
import json
import secrets

import pytest
from pydantic import ValidationError

from app.agent.contracts import (ActionResult, ActionSpec, ActionStarted, DoneFrame, RunEnded, TextDelta, TextFrame,
                                 sse)
from app.agent.guard import LeakGuard
from app.agent.outcomes import action_outcome
from app.agent.turn import (Runtime, RuntimeUnavailable, Stats, TurnPolicy, call_with_retry, run_turn)
from app.capacity import Capacity

ACTIONS = {
    "search_catalog": ActionSpec(name="search_catalog", label="Searching the catalog"),
    "save_plan": ActionSpec(name="save_plan", label="Saving your plan",
                            failure_messages={"plan_locked": "That plan is locked, so it was not changed."}),
}
FAST = TurnPolicy(total_s=2, idle_s=0.2, start_attempts=2, retry_wait_s=0, cleanup_s=0.5)


def canary() -> str:
    return "CANARY-" + secrets.token_hex(8)


class Script:
    """A fake runtime stream. Items are events to yield, exceptions to raise, or asyncio.Event gates to wait on."""

    def __init__(self, *items):
        self.items = items
        self.closed = False
        self.yielded = 0

    async def _gen(self):
        try:
            for item in self.items:
                if isinstance(item, asyncio.Event):
                    await item.wait()
                elif isinstance(item, BaseException):
                    raise item
                else:
                    self.yielded += 1
                    yield item
        finally:
            self.closed = True

    def runtime(self, **kw):
        async def start():
            return self._gen()
        return Runtime(start=start, **kw)


def play(runtime, guard=None, capacity=None, policy=FAST, stats=None):
    async def go():
        return [f async for f in run_turn(runtime, ACTIONS, guard or LeakGuard([]), capacity or Capacity(5), policy,
                                          stats.add if stats else None)]
    return asyncio.run(go())


def done(frames) -> DoneFrame:
    assert isinstance(frames[-1], DoneFrame) and sum(isinstance(f, DoneFrame) for f in frames) == 1
    return frames[-1]


def actions(frames):
    return [(f.seq, f.status) for f in frames if f.type == "action"]


def text(frames):
    return "".join(f.text for f in frames if isinstance(f, TextFrame))


def wire(frames) -> str:
    return "".join(sse(f) for f in frames)


@pytest.mark.parametrize("result, expected", [
    ({"success": True}, ("succeeded", None)),
    ('{"success": true, "plan_id": "p1"}', ("succeeded", None)),
    ({"success": False, "error": {"code": "plan_locked", "detail": "row 7"}}, ("failed", "plan_locked")),
    ({"success": True, "error": "half done"}, ("failed", None)),
    ({"error": {"code": 5}}, ("failed", None)),
    ({"plan_id": "p1"}, ("unconfirmed", None)),
    ("Rejected: invalid run token.", ("unconfirmed", None)),
    (None, ("unconfirmed", None)),
    (["success", True], ("unconfirmed", None)),
    ({"success": "true"}, ("unconfirmed", None)),
])
def test_only_an_explicit_flag_decides_an_action(result, expected):
    assert action_outcome(result) == expected


def test_a_failed_action_in_a_completed_turn_stays_failed():
    frames = play(Script(ActionStarted(call_id="c1", action="save_plan"),
                         ActionResult(call_id="c1", result={"success": False, "error": {"code": "plan_locked"}}),
                         TextDelta(text="All set!"), RunEnded(status="completed")).runtime())
    end = done(frames)
    assert end.turn == "completed" and end.failed == 1 and end.succeeded == 0 and end.fallback is None
    assert actions(frames) == [(1, "started"), (1, "failed")]
    assert "locked" in [f for f in frames if f.type == "action"][-1].message


def test_a_completed_run_never_confirms_an_action_that_sent_no_result():
    frames = play(Script(ActionStarted(call_id="c1", action="save_plan"), RunEnded(status="completed")).runtime())
    assert actions(frames) == [(1, "started"), (1, "unconfirmed")] and done(frames).unconfirmed == 1


def test_raw_tool_output_and_runtime_ids_never_reach_the_browser():
    secret_row = "internal row 7 owner@example.com"
    frames = play(Script(ActionStarted(call_id="hermes-call-xyz", action="search_catalog"),
                         ActionResult(call_id="hermes-call-xyz", result={"success": False, "error": {"code": "x", "message": secret_row}}),
                         RunEnded(status="completed")).runtime())
    out = wire(frames)
    assert secret_row not in out and "hermes-call-xyz" not in out


def test_an_unlisted_action_is_reported_as_not_allowed_and_its_name_is_hidden():
    frames = play(Script(ActionStarted(call_id="c1", action="terminal"), ActionResult(call_id="c1", result={"success": True}),
                         RunEnded(status="completed")).runtime())
    acts = [f for f in frames if f.type == "action"]
    assert [(a.action, a.status) for a in acts] == [(None, "failed")] and "terminal" not in wire(frames)
    assert done(frames).failed == 1 and done(frames).succeeded == 0


def test_a_repeated_result_counts_once():
    frames = play(Script(ActionStarted(call_id="c1", action="search_catalog"),
                         ActionResult(call_id="c1", result={"success": True}),
                         ActionResult(call_id="c1", result={"success": False}),
                         RunEnded(status="completed")).runtime())
    assert done(frames).succeeded == 1 and done(frames).failed == 0


@pytest.mark.parametrize("status, notice", [("failed", "run_failed"), ("cancelled", "run_cancelled")])
def test_a_failed_or_cancelled_run_hands_back_to_browsing(status, notice):
    frames = play(Script(TextDelta(text="Let me look"), RunEnded(status=status)).runtime())
    assert done(frames).turn == status and done(frames).fallback == "browse"
    assert [f.code for f in frames if f.type == "notice"] == [notice]


def test_a_canary_split_across_deltas_is_caught():
    value = canary()
    parts = [value[i:i + 5] for i in range(0, len(value), 5)]
    stream = Script(TextDelta(text="Your token is "), *[TextDelta(text=p) for p in parts], TextDelta(text=" ok"),
                    RunEnded(status="completed"))
    frames = play(stream.runtime(), LeakGuard([value]))
    out = wire(frames)
    assert value not in out and value[:9] not in out and done(frames).turn == "blocked" and stream.closed
    assert done(frames).fallback == "browse"


@pytest.mark.parametrize("ending", ["completed", "failed", "drop", "idle"])
def test_a_nearly_complete_canary_is_blocked_whatever_ends_the_run(ending):
    value = canary()
    gate = asyncio.Event()
    tail = {"completed": [RunEnded(status="completed")], "failed": [RunEnded(status="failed")],
            "drop": [ConnectionError("gone")], "idle": [gate]}[ending]
    frames = play(Script(TextDelta(text="safe start "), TextDelta(text=value[:-1]), *tail).runtime(), LeakGuard([value]))
    out = wire(frames)
    assert not any(value[i:i + 8] in out for i in range(len(value) - 7))
    assert done(frames).turn == "blocked" and done(frames).fallback == "browse"


def test_a_canary_whose_last_char_arrives_late_still_blocks():
    value = canary()
    frames = play(Script(TextDelta(text=value[:-1]), TextDelta(text=value[-1]), RunEnded(status="completed")).runtime(),
                  LeakGuard([value]))
    assert value not in wire(frames) and done(frames).turn == "blocked"


def test_a_partial_echo_of_the_canary_is_a_leak():
    value = canary()
    frames = play(Script(TextDelta(text="it was " + value[4:13] + " I think"), RunEnded(status="completed")).runtime(),
                  LeakGuard([value]))
    assert value[4:13] not in wire(frames) and done(frames).turn == "blocked"


def test_clean_text_streams_through_unchanged():
    value = canary()
    words = ["Here ", "is ", "what ", "I ", "found."]
    frames = play(Script(*[TextDelta(text=w) for w in words], RunEnded(status="completed")).runtime(), LeakGuard([value]))
    assert text(frames) == "".join(words) and done(frames).turn == "completed"


def test_guarded_values_must_be_long_enough_to_mean_something():
    with pytest.raises(ValueError):
        LeakGuard(["short"])


def test_an_idle_runtime_times_out_closes_the_stream_and_frees_capacity():
    cap = Capacity(1)
    gate = asyncio.Event()
    stream = Script(TextDelta(text="Thinking"), gate, RunEnded(status="completed"))
    stats = Stats()
    frames = play(stream.runtime(), capacity=cap, stats=stats)
    assert done(frames).turn == "timed_out" and done(frames).fallback == "browse"
    assert [f.code for f in frames if f.type == "notice"] == ["timeout"]
    assert stream.closed and cap.usage().running == 0 and cap.usage().stopping == 0
    assert stats.records[0].status == "timed_out" and stats.records[0].cleanup_confirmed


def test_the_total_deadline_applies_even_when_events_keep_coming():
    async def chatter():
        while True:
            await asyncio.sleep(0.01)
            yield TextDelta(text=".")

    async def start():
        return chatter()

    frames = play(Runtime(start=start), policy=TurnPolicy(total_s=0.2, idle_s=1, retry_wait_s=0, cleanup_s=0.5))
    assert done(frames).turn == "timed_out"


def test_a_stopping_turn_keeps_its_slot_until_cleanup_finishes():
    cap = Capacity(1)
    seen = {}

    class Stuck:
        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.Event().wait()

        async def aclose(self):
            seen["during_cleanup"] = cap.try_claim()
            seen["usage"] = cap.usage()

    async def start():
        return Stuck()

    async def scenario():
        frames = [f async for f in run_turn(Runtime(start=start), ACTIONS, LeakGuard([]), cap, FAST)]
        seen["after"] = cap.try_claim()
        return frames

    frames = asyncio.run(scenario())
    assert done(frames).turn == "timed_out"
    assert seen["during_cleanup"] is None and seen["usage"].stopping == 1
    assert seen["after"] is not None


def test_a_busy_app_rejects_politely_and_the_rejection_is_not_a_success():
    cap = Capacity(1)
    held = cap.try_claim()
    stats = Stats()
    frames = play(Script(RunEnded(status="completed")).runtime(), capacity=cap, stats=stats)
    assert done(frames).turn == "rejected" and done(frames).fallback == "browse"
    assert [f.code for f in frames if f.type == "notice"] == ["busy"]
    held.release()
    play(Script(TextDelta(text="hi"), RunEnded(status="completed")).runtime(), capacity=cap, stats=stats)
    summary = stats.summary()
    assert summary["turns"] == 2 and summary["completed"] == 1 and summary["rejected"] == 1


def test_a_mid_stream_drop_is_interrupted_and_open_actions_are_unconfirmed():
    cap = Capacity(1)
    frames = play(Script(ActionStarted(call_id="c1", action="save_plan"), ConnectionError("reset")).runtime(), capacity=cap)
    assert done(frames).turn == "interrupted" and actions(frames)[-1] == (1, "unconfirmed")
    assert "reset" not in wire(frames) and cap.usage().running == 0


def test_a_stream_that_ends_without_a_run_status_is_not_completed():
    frames = play(Script(TextDelta(text="Partial")).runtime())
    assert done(frames).turn == "interrupted" and done(frames).fallback == "browse"


def test_an_unreachable_runtime_is_unavailable_with_no_detail_leaked():
    calls = []

    async def start():
        calls.append(1)
        raise RuntimeUnavailable("http://hermes:8642 refused, key=abc")

    frames = play(Runtime(start=start, duplicate_safe_start=True))
    assert done(frames).turn == "unavailable" and len(calls) == FAST.start_attempts
    assert "hermes" not in wire(frames) and "key" not in wire(frames)


def test_starting_a_run_is_not_retried_without_duplicate_protection():
    calls = []

    async def start():
        calls.append(1)
        raise RuntimeUnavailable("lost reply")

    play(Runtime(start=start))
    assert calls == [1]


def test_a_read_is_retried_but_stops_at_the_bound():
    calls = []

    async def read():
        calls.append(1)
        raise RuntimeUnavailable

    with pytest.raises(RuntimeUnavailable):
        asyncio.run(call_with_retry(read, attempts=3, write=False, duplicate_safe=False, wait_s=0))
    assert len(calls) == 3


def test_an_unexpected_start_error_still_frees_capacity():
    cap = Capacity(1)

    async def start():
        raise KeyError("boom")

    with pytest.raises(KeyError):
        play(Runtime(start=start), capacity=cap)
    assert cap.usage().running == 0 and cap.try_claim() is not None


def test_a_browser_that_leaves_mid_turn_frees_capacity_and_closes_the_stream():
    cap = Capacity(1)
    stream = Script(TextDelta(text="one"), TextDelta(text="two"), RunEnded(status="completed"))

    async def scenario():
        gen = run_turn(stream.runtime(), ACTIONS, LeakGuard([]), cap, FAST)
        await gen.__anext__()
        await gen.aclose()

    asyncio.run(scenario())
    assert stream.closed and cap.usage().running == 0


def test_every_frame_is_valid_json_with_a_known_type():
    frames = play(Script(TextDelta(text="hi"), ActionStarted(call_id="c", action="search_catalog"),
                         ActionResult(call_id="c", result={"success": True}), RunEnded(status="completed")).runtime())
    for chunk in wire(frames).split("\n\n")[:-1]:
        assert json.loads(chunk.removeprefix("data: "))["type"] in {"text", "action", "notice", "done"}


def test_runtime_events_reject_unknown_fields():
    with pytest.raises(ValidationError):
        TextDelta(text="x", preview="raw tool output")


def test_turn_limits_must_be_positive():
    with pytest.raises(ValueError):
        TurnPolicy(total_s=0)
