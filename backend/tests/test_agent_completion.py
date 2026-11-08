import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import adoption, chat, db
from app.agent import bindings, completion
from app.agent.chat_actions import RunGate
from app.agent.completion import ActionReport, Completion, ExpectedAction, check_tools, finalize, plan_request_id
from app.agent.contracts import (ActionFrame, ActionResult, ActionSpec, ActionStarted, DoneFrame, NoticeFrame, RunEnded,
                                 TextDelta, TextFrame)
from app.agent.guard import LeakGuard
from app.agent.turn import Runtime, TurnPolicy, run_turn
from app.auth import Principal
from app.capacity import Capacity
from app.schemas import BusinessProfile, Selection
from conftest import account_header
from test_chat_bindings import frames, rows, script

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
ALICE = Principal("11111111-1111-1111-1111-111111111111", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
BOB = Principal("22222222-2222-2222-2222-222222222222", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PLAN = {"problem_ids": ["job_scheduling"], "tool_ids": ["jobber"]}
OTHER_PLAN = {"problem_ids": ["job_scheduling"], "tool_ids": ["housecall_pro"]}
PROFILE = BusinessProfile(trade="hvac")
SAVE = ExpectedAction("save_plan")
CATALOG = db.load_catalog_file(Path(__file__).resolve().parents[1] / "data" / "catalog.json")


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "completion.db")
    bindings.ensure_schema(connection)
    return connection


def gate(conn, principal=ALICE):
    return RunGate(conn, None, principal, "conv-1", now=lambda: NOW)


def redeemed(conn, g, call_id="call-1", arguments=PLAN):
    token = bindings.issue_receipt(conn, g.binding, call_id, "save_plan", arguments, NOW)
    bindings.redeem(conn, token, g.principal, "save_plan", arguments, NOW)
    return token


def write_plan(conn, g, call_id="call-1", arguments=PLAN):
    selection = Selection.model_validate({**arguments, "profile": PROFILE.model_dump(mode="json")})
    return adoption.save_plan(conn, CATALOG, g.binding.owner_hash, plan_request_id(g.binding.run_id, call_id), selection, NOW)[0]


def plan_count(conn):
    return conn.execute("SELECT COUNT(*) FROM adoption_plan").fetchone()[0]


def only(done):
    assert len(done.actions) == 1
    return done.actions[0]


def test_a_completed_run_with_no_save_did_not_save(conn):
    done = finalize(conn, None, gate(conn).binding, [SAVE])
    assert only(done).status == "not_executed" and done.code == "action_not_executed"
    assert done.deliver and not done.succeeded("save_plan")


def test_a_public_answer_that_needed_no_action_is_delivered_clean(conn):
    done = finalize(conn, None, gate(conn).binding)
    assert done.deliver and done.actions == () and done.code is None


def test_guest_run_reports_an_expected_save_as_not_run(conn):
    done = finalize(conn, None, gate(conn, Principal()).binding, [SAVE])
    assert only(done).status == "not_executed" and done.deliver


def test_a_failed_receipt_is_reported_failed(conn):
    g = gate(conn)
    data = g.private_action(CATALOG, "call-1", "save_plan", {"problem_ids": ["job_scheduling"], "tool_ids": ["no_such_tool"]}, PROFILE)
    assert data["outcome"] == "failed"
    done = finalize(conn, None, g.binding, [SAVE])
    assert only(done).status == "failed" and done.code == "action_failed" and plan_count(conn) == 0


def test_a_receipt_that_was_issued_but_never_redeemed_did_not_run(conn):
    g = gate(conn)
    bindings.issue_receipt(conn, g.binding, "call-1", "save_plan", PLAN, NOW)
    assert only(finalize(conn, None, g.binding, [SAVE])).status == "not_executed"


def test_a_redeemed_receipt_with_no_outcome_and_no_effect_is_unconfirmed_not_failed(conn):
    g = gate(conn)
    redeemed(conn, g)
    report = only(finalize(conn, None, g.binding, [SAVE]))
    assert report.status == "unconfirmed" and "Nothing was changed" not in report.message


def test_a_stored_success_without_the_saved_plan_is_not_trusted(conn):
    g = gate(conn)
    token = redeemed(conn, g)
    bindings.record_outcome(conn, token, {"success": True})
    assert only(finalize(conn, None, g.binding, [SAVE])).status == "unconfirmed"


def test_a_crash_after_the_write_reconciles_to_success_and_never_writes_twice(conn):
    g = gate(conn)
    redeemed(conn, g)
    plan = write_plan(conn, g)
    report = only(finalize(conn, None, g.binding, [SAVE]))
    assert report.status == "succeeded" and report.ref == plan.id
    assert "already ran" in g.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)["error"]
    assert plan_count(conn) == 1


def test_private_action_that_raises_after_the_insert_reports_the_save_it_made(conn, monkeypatch):
    original = adoption.save_plan

    def lands_then_breaks(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("connection dropped")
    monkeypatch.setattr(adoption, "save_plan", lands_then_breaks)
    g = gate(conn)
    data = g.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)
    assert data["outcome"] == "succeeded" and data["saved"]
    assert conn.execute("SELECT outcome FROM action_receipt").fetchone()[0] == "succeeded"
    assert only(finalize(conn, None, g.binding, [SAVE])).ref == data["saved"] and plan_count(conn) == 1


def test_private_action_that_raises_with_an_unknown_effect_says_so_and_does_not_retry(conn, monkeypatch):
    calls = []

    def breaks(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("timeout")
    monkeypatch.setattr(adoption, "save_plan", breaks)
    g = gate(conn)
    data = g.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)
    assert data["outcome"] == "unconfirmed" and "not saved" not in data["error"] and len(calls) == 1
    assert conn.execute("SELECT outcome FROM action_receipt").fetchone()[0] == "unconfirmed"
    assert only(finalize(conn, None, g.binding, [SAVE])).status == "unconfirmed"


def test_private_action_whose_outcome_cannot_be_recorded_falls_back_to_the_effect(conn, monkeypatch):
    def locked(*args):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(bindings, "record_outcome", locked)
    g = gate(conn)
    data = g.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)
    assert data["outcome"] == "succeeded"
    assert conn.execute("SELECT outcome FROM action_receipt").fetchone()[0] is None
    assert only(finalize(conn, None, g.binding, [SAVE])).status == "succeeded"


def test_another_accounts_or_runs_receipts_are_never_counted(conn):
    alice, bob = gate(conn), gate(conn, BOB)
    assert alice.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)["outcome"] == "succeeded"
    assert only(finalize(conn, None, bob.binding, [SAVE])).status == "not_executed"
    assert only(finalize(conn, None, gate(conn).binding, [SAVE])).status == "not_executed"


def test_a_save_with_different_arguments_does_not_satisfy_the_expected_one(conn):
    g = gate(conn)
    g.private_action(CATALOG, "call-1", "save_plan", OTHER_PLAN, PROFILE)
    done = finalize(conn, None, g.binding, [ExpectedAction("save_plan", arguments=PLAN)])
    expected, extra = done.actions
    assert expected.status == "not_executed" and expected.expected
    assert extra.status == "succeeded" and not extra.expected


def test_an_expired_receipt_did_not_run(conn):
    g = gate(conn)
    token = bindings.issue_receipt(conn, g.binding, "call-1", "save_plan", PLAN, NOW, seconds=1)
    with pytest.raises(bindings.BindingDenied):
        bindings.redeem(conn, token, ALICE, "save_plan", PLAN, NOW + timedelta(seconds=5))
    assert only(finalize(conn, None, g.binding, [SAVE])).status == "not_executed"


def test_a_replayed_call_adds_no_second_save_or_report(conn):
    g = gate(conn)
    g.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)
    g.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)
    assert only(finalize(conn, None, g.binding)).status == "succeeded" and plan_count(conn) == 1


def test_logout_before_the_final_answer_withholds_it(conn):
    g = gate(conn)
    g.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)
    with conn:
        conn.execute("INSERT INTO revoked_auth_session VALUES(?,?,?)", (ALICE.session_id, ALICE.user_id, NOW.isoformat()))
    done = finalize(conn, None, g.binding, [SAVE])
    assert not done.deliver and done.code == "session_ended"


def test_a_partial_multi_action_run_keeps_the_known_save_and_the_uncertain_one(conn):
    g = gate(conn)
    g.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)
    redeemed(conn, g, "call-2", OTHER_PLAN)
    done = finalize(conn, None, g.binding, [SAVE, SAVE])
    assert [a.status for a in done.actions] == ["succeeded", "unconfirmed"]
    assert done.code == "action_unconfirmed" and done.succeeded("save_plan")


ADVERTISED = "mcp__marketplace__get_tool_details"
DETAILS_SCHEMA = {"type": "object", "properties": {"tool_id": {"type": "string"}, "operation": {"type": "string"}},
                  "required": ["tool_id", "operation"]}


@pytest.mark.parametrize("available, code", [
    ([], "tool_unavailable"),
    (["mcp__marketplace__compare_tools"], "untrusted_tool"),
    ([ADVERTISED], None),
    ([ADVERTISED, "mcp__other__get_tool_details"], "untrusted_tool"),
    (["mcp__other__get_tool_details"], "untrusted_tool"),
    (["get_tool_details"], "untrusted_tool"),
    ([ADVERTISED, "mcp__marketplace__save_plan"], "private_tool_exposed"),
])
def test_advertised_tools_must_match_the_trusted_inventory_exactly(available, code):
    assert check_tools(["get_tool_details"], available) == code


def test_the_mcp_server_list_is_checked_against_its_own_exact_names():
    assert check_tools(["get_tool_details"], {"get_tool_details": DETAILS_SCHEMA}, layer="listed") is None
    assert check_tools(["get_tool_details"], {ADVERTISED: DETAILS_SCHEMA}, layer="listed") == "untrusted_tool"


def test_a_tool_whose_arguments_changed_is_not_the_trusted_tool():
    changed = {"type": "object", "properties": {"tool_id": {}, "operation": {}, "account_id": {}}}
    assert check_tools(["get_tool_details"], {ADVERTISED: changed}) == "tool_unavailable"
    model_form = {"type": "function", "function": {"name": ADVERTISED, "parameters": DETAILS_SCHEMA}}
    assert check_tools(["get_tool_details"], {ADVERTISED: model_form}) is None


def test_the_server_registers_an_expected_save_bound_to_this_run(conn):
    g = gate(conn)
    op = g.expect("save_plan", PLAN)
    assert g.expected == [op] and op.run_id == g.binding.run_id
    assert op.arguments_hash == bindings.arguments_hash(PLAN)


@pytest.mark.parametrize("principal, action, arguments, code", [
    (Principal(), "save_plan", PLAN, "sign_in_required"),
    (ALICE, "get_tool_details", {"tool_id": "jobber"}, "not_allowed"),
    (ALICE, "delete_account", {}, "not_allowed"),
    (ALICE, "save_plan", {"problem_ids": "nope"}, "invalid_arguments"),
    (ALICE, "save_plan", {**PLAN, "account_id": "x"}, "forged_binding"),
])
def test_the_server_refuses_to_register_what_it_would_not_run(conn, principal, action, arguments, code):
    g = gate(conn, principal)
    with pytest.raises(bindings.BindingDenied) as exc:
        g.expect(action, arguments)
    assert exc.value.code == code and g.expected == []


def test_a_registered_save_with_zero_calls_did_not_run(conn):
    g = gate(conn)
    g.expect("save_plan", PLAN)
    done = finalize(conn, None, g.binding, g.expected)
    assert [(a.action, a.status) for a in done.actions] == [("save_plan", "not_executed")]


def test_a_registered_save_is_matched_by_its_server_hash(conn):
    g = gate(conn)
    g.expect("save_plan", PLAN)
    g.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)
    assert only(finalize(conn, None, g.binding, g.expected)).status == "succeeded"
    other = gate(conn)
    other.expect("save_plan", OTHER_PLAN)
    other.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)
    statuses = sorted(a.status for a in finalize(conn, None, other.binding, other.expected).actions)
    assert statuses == ["not_executed", "succeeded"]


def test_an_expectation_from_another_run_never_matches(conn):
    g, later = gate(conn), gate(conn)
    stale = g.expect("save_plan", PLAN)
    later.private_action(CATALOG, "call-1", "save_plan", PLAN, PROFILE)
    reports = finalize(conn, None, later.binding, [stale]).actions
    assert [(a.status, a.expected) for a in reports] == [("not_executed", True), ("succeeded", False)]


SPECS = {"get_tool_details": ActionSpec(name="get_tool_details", label="Looking up a tool"),
         "save_plan": ActionSpec(name="save_plan", label="Saving your plan")}
FAST = TurnPolicy(total_s=2, idle_s=0.3, start_attempts=1, retry_wait_s=0, cleanup_s=0.5)


def consume(events, settle):
    async def start():
        async def gen():
            for event in events:
                if isinstance(event, BaseException):
                    raise event
                if isinstance(event, asyncio.Event):
                    await event.wait()
                    continue
                yield event
        return gen()

    async def go():
        return [f async for f in run_turn(Runtime(start=start), SPECS, LeakGuard([]), Capacity(5), FAST, settle=settle)]
    return asyncio.run(go())


def by_type(frames_, kind):
    return [f for f in frames_ if isinstance(f, kind)]


class Spy:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def __call__(self):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def test_the_consumer_settles_private_steps_from_the_finalizer_not_the_runtime():
    spy = Spy(Completion(True, (ActionReport("save_plan", "call-1", "unconfirmed", True),)))
    out = consume([ActionStarted(call_id="call-1", action="save_plan"),
                   ActionResult(call_id="call-1", result={"success": True}),
                   TextDelta(text="Your plan is saved."), RunEnded(status="completed")], spy)
    assert spy.calls == 1
    assert [f.status for f in by_type(out, ActionFrame)] == ["started", "unconfirmed"]
    done = by_type(out, DoneFrame)[0]
    assert done.succeeded == 0 and done.unconfirmed == 1 and done.code == "action_unconfirmed"


def test_hermes_completing_with_zero_tools_cannot_claim_the_save():
    spy = Spy(Completion(True, (ActionReport("save_plan", None, "not_executed", True),)))
    out = consume([TextDelta(text="Done! Saved."), RunEnded(status="completed")], spy)
    action = by_type(out, ActionFrame)[0]
    assert action.status == "failed" and "did not run" in action.message
    assert by_type(out, DoneFrame)[0].code == "action_not_executed"


def test_a_failing_finalizer_withholds_the_answer_and_leaves_the_save_unconfirmed():
    out = consume([ActionStarted(call_id="call-1", action="save_plan"), ActionResult(call_id="call-1", result={"success": True}),
                   TextDelta(text="Saved."), RunEnded(status="completed")], Spy(sqlite3.OperationalError("locked")))
    assert by_type(out, TextFrame) == []
    assert by_type(out, ActionFrame)[-1].status == "unconfirmed"
    assert by_type(out, DoneFrame)[0].code == "action_unconfirmed"


def test_the_consumer_withholds_the_answer_after_logout():
    out = consume([TextDelta(text="Here is your answer."), RunEnded(status="completed")], Spy(Completion(False)))
    assert by_type(out, TextFrame) == []
    assert [n.code for n in by_type(out, NoticeFrame)] == ["session_ended"]


def test_the_consumer_delivers_a_public_answer_that_needed_no_action():
    spy = Spy(Completion(True))
    out = consume([ActionStarted(call_id="c", action="get_tool_details"), ActionResult(call_id="c", result={"success": True}),
                   TextDelta(text="Jobber schedules jobs."), RunEnded(status="completed")], spy)
    assert [f.text for f in by_type(out, TextFrame)] == ["Jobber schedules jobs."]
    assert by_type(out, DoneFrame)[0].code is None and by_type(out, DoneFrame)[0].succeeded == 1


def test_a_timed_out_run_keeps_a_save_that_did_land():
    spy = Spy(Completion(True, (ActionReport("save_plan", "call-1", "succeeded", True, "plan-1"),)))
    out = consume([ActionStarted(call_id="call-1", action="save_plan"), asyncio.Event()], spy)
    assert by_type(out, DoneFrame)[0].turn == "timed_out"
    assert by_type(out, ActionFrame)[-1].status == "succeeded"


def test_a_disconnected_run_with_an_unknown_save_stays_unconfirmed():
    spy = Spy(Completion(True, (ActionReport("save_plan", "call-1", "unconfirmed", True),)))
    out = consume([ActionStarted(call_id="call-1", action="save_plan"), ConnectionError("gone")], spy)
    assert by_type(out, DoneFrame)[0].turn == "interrupted"
    assert by_type(out, ActionFrame)[-1].status == "unconfirmed" and "Nothing was changed" not in by_type(out, ActionFrame)[-1].message


BODY = {"conversation_id": "fixture", "message": "Save my plan please", "profile": {"trade": "hvac"}}
CHAT_PLAN = {"problem_ids": ["missed_calls"], "tool_ids": ["jobber"]}


def actions(events):
    return [e for e in events if e["type"] == "action"]


def test_the_chat_route_reports_a_save_from_the_stored_receipt(client, monkeypatch):
    script(monkeypatch, [[("call-1", "save_plan", CHAT_PLAN)]], [])
    events = frames(client.post("/api/chat", headers=account_header(1, 1), json=BODY))
    assert [(a["action"], a["status"]) for a in actions(events)] == [("save_plan", "succeeded")]
    assert events.index(actions(events)[0]) < next(i for i, e in enumerate(events) if e["type"] == "message_delta")


def test_the_chat_route_reports_an_unknown_effect_as_unconfirmed(client, monkeypatch):
    monkeypatch.setattr(adoption, "save_plan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout")))
    script(monkeypatch, [[("call-1", "save_plan", CHAT_PLAN)]], [])
    events = frames(client.post("/api/chat", headers=account_header(1, 1), json=BODY))
    action = actions(events)[0]
    assert action["status"] == "unconfirmed" and action["code"] == "action_unconfirmed"
    assert "Nothing was changed" not in action["message"]
    assert rows(client, "SELECT COUNT(*) FROM adoption_plan") == [(0,)]


def test_the_chat_route_delivers_a_public_answer_with_no_action_events(client, monkeypatch):
    script(monkeypatch, [], [])
    events = frames(client.post("/api/chat", headers=account_header(1, 1), json=BODY))
    assert actions(events) == [] and any(e["type"] == "message_delta" for e in events)


def test_the_chat_route_calls_the_finalizer_and_fails_closed_when_it_breaks(client, monkeypatch):
    spy = []

    def broken(*args, **kwargs):
        spy.append(1)
        raise sqlite3.OperationalError("locked")
    monkeypatch.setattr(chat, "finalize", broken)
    script(monkeypatch, [[("call-1", "save_plan", CHAT_PLAN)]], [])
    events = frames(client.post("/api/chat", headers=account_header(1, 1), json=BODY))
    assert spy == [1]
    assert not any(e["type"] == "message_delta" for e in events)
    assert any(e.get("code") == "agent_unavailable" for e in events)


def test_the_chat_route_reports_a_registered_save_that_never_ran(client, monkeypatch):
    monkeypatch.setattr(chat, "register_expected", lambda gate, body: gate.expect("save_plan", CHAT_PLAN))
    script(monkeypatch, [], [])
    events = frames(client.post("/api/chat", headers=account_header(1, 1), json=BODY))
    assert [(a["action"], a["status"], a["code"]) for a in actions(events)] == [("save_plan", "not_executed", "action_not_executed")]
    assert rows(client, "SELECT COUNT(*) FROM adoption_plan") == [(0,)]


def test_the_chat_route_refuses_a_guest_registration_before_any_model_call(client, monkeypatch):
    monkeypatch.setattr(chat, "register_expected", lambda gate, body: gate.expect("save_plan", CHAT_PLAN))
    script(monkeypatch, [], [])
    called = []
    monkeypatch.setattr(chat, "_conversation", lambda *a: called.append(1))
    events = frames(client.post("/api/chat", json=BODY))
    assert called == [] and [e.get("code") for e in events if e["type"] == "error"] == ["sign_in_required"]


def test_a_guest_catalog_turn_registers_nothing_and_is_delivered_clean(client, monkeypatch):
    script(monkeypatch, [], [])
    events = frames(client.post("/api/chat", json=BODY))
    assert actions(events) == [] and any(e["type"] == "message_delta" for e in events)
    assert not any(e["type"] == "error" for e in events)


def test_the_chat_route_uses_the_real_finalizer(client, monkeypatch):
    seen = []
    real = completion.finalize
    monkeypatch.setattr(chat, "finalize", lambda *a, **k: seen.append(a[2]) or real(*a, **k))
    script(monkeypatch, [], [])
    client.post("/api/chat", headers=account_header(1, 1), json=BODY)
    assert len(seen) == 1 and seen[0].private
