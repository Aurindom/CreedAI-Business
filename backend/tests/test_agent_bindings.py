from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.agent import bindings
from app.agent.bindings import BindingDenied
from app.auth import Principal

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
ALICE = Principal("11111111-1111-1111-1111-111111111111", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ALICE_OTHER_SESSION = Principal(ALICE.user_id, "cccccccc-cccc-cccc-cccc-cccccccccccc")
BOB = Principal("22222222-2222-2222-2222-222222222222", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
GUEST = Principal()
PLAN = {"tool_ids": ["mailchimp"], "tasks": ["email_marketing"]}


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "bindings.db")
    bindings.ensure_schema(connection)
    return connection


def logout(conn, principal):
    with conn:
        conn.execute("INSERT INTO revoked_auth_session VALUES(?,?,?)", (principal.session_id, principal.user_id, NOW.isoformat()))


def receipt_for(conn, principal=ALICE, arguments=PLAN, call_id="call-1", seconds=bindings.RECEIPT_SECONDS):
    run = bindings.bind_run(conn, principal, "conv-1", NOW)
    return run, bindings.issue_receipt(conn, run, call_id, "save_plan", arguments, NOW, seconds)


def denied(code, function, *args):
    with pytest.raises(BindingDenied) as caught:
        function(*args)
    assert caught.value.code == code


def test_same_account_action_succeeds_and_binding_comes_from_server_rows(conn):
    run, token = receipt_for(conn)
    redeemed = bindings.redeem(conn, token, ALICE, "save_plan", PLAN, NOW + timedelta(seconds=5))
    assert redeemed == run
    owner_rows = conn.execute("SELECT owner_hash, business_id FROM account_owner WHERE user_id=?", (ALICE.user_id,)).fetchone()
    assert (redeemed.owner_hash, redeemed.business_id) == owner_rows


def test_another_account_cannot_use_the_receipt_and_does_not_burn_it(conn):
    _, token = receipt_for(conn)
    bindings.bind_run(conn, BOB, "conv-1", NOW)
    denied("wrong_account", bindings.redeem, conn, token, BOB, "save_plan", PLAN, NOW)
    assert bindings.redeem(conn, token, ALICE, "save_plan", PLAN, NOW).user_id == ALICE.user_id


def test_two_accounts_with_the_same_conversation_id_get_separate_businesses(conn):
    alice = bindings.bind_run(conn, ALICE, "conv-1", NOW)
    bob = bindings.bind_run(conn, BOB, "conv-1", NOW)
    assert alice.business_id != bob.business_id and alice.owner_hash != bob.owner_hash


@pytest.mark.parametrize("field", ["owner_hash", "business_id", "user_id", "session_id", "receipt"])
def test_model_or_frontend_identity_fields_are_rejected_as_forgery(conn, field):
    run = bindings.bind_run(conn, ALICE, "conv-1", NOW)
    forged = dict(PLAN, **{field: "someone-else"})
    denied("forged_binding", bindings.authorize, run, "save_plan", forged)
    denied("forged_binding", bindings.authorize, run, "recommend_tools", forged)
    denied("forged_binding", bindings.issue_receipt, conn, run, "call-1", "save_plan", forged, NOW)


def test_changed_arguments_or_action_do_not_match_the_receipt(conn):
    _, token = receipt_for(conn)
    denied("action_mismatch", bindings.redeem, conn, token, ALICE, "save_plan", {"tool_ids": ["toast"], "tasks": ["email_marketing"]}, NOW)
    denied("action_mismatch", bindings.redeem, conn, token, ALICE, "delete_plan", PLAN, NOW)


def test_unknown_or_guessed_receipt_fails(conn):
    receipt_for(conn)
    denied("unknown_receipt", bindings.redeem, conn, "not-a-real-receipt", ALICE, "save_plan", PLAN, NOW)
    denied("unknown_receipt", bindings.redeem, conn, None, ALICE, "save_plan", PLAN, NOW)


def test_expired_receipt_fails(conn):
    _, token = receipt_for(conn, seconds=30)
    denied("expired", bindings.redeem, conn, token, ALICE, "save_plan", PLAN, NOW + timedelta(seconds=30))


def test_replay_fails(conn):
    _, token = receipt_for(conn)
    bindings.redeem(conn, token, ALICE, "save_plan", PLAN, NOW)
    denied("replayed", bindings.redeem, conn, token, ALICE, "save_plan", PLAN, NOW)


def test_one_receipt_per_tool_call(conn):
    run, _ = receipt_for(conn)
    denied("duplicate_call", bindings.issue_receipt, conn, run, "call-1", "save_plan", PLAN, NOW)


def test_logout_blocks_new_runs_new_receipts_redemption_and_delivery(conn):
    run, token = receipt_for(conn)
    logout(conn, ALICE)
    denied("session_ended", bindings.bind_run, conn, ALICE, "conv-1", NOW)
    denied("session_ended", bindings.issue_receipt, conn, run, "call-2", "save_plan", PLAN, NOW)
    denied("session_ended", bindings.redeem, conn, token, ALICE, "save_plan", PLAN, NOW)
    assert bindings.may_deliver(conn, run) is False


def test_receipt_is_bound_to_the_session_that_issued_it(conn):
    _, token = receipt_for(conn)
    denied("session_ended", bindings.redeem, conn, token, ALICE_OTHER_SESSION, "save_plan", PLAN, NOW)


def test_conversation_past_its_recovery_window_cannot_be_bound(conn):
    with conn:
        conn.execute("INSERT INTO chat_conversation VALUES(?,?,?,?,?)",
                     (ALICE.user_id, "conv-old", ALICE.session_id, NOW.isoformat(), (NOW - timedelta(seconds=1)).isoformat()))
    denied("conversation_closed", bindings.bind_run, conn, ALICE, "conv-old", NOW)


def test_guest_keeps_public_catalog_but_private_actions_fail(conn):
    guest = bindings.bind_run(conn, GUEST, "conv-g", NOW)
    assert isinstance(guest, bindings.PublicBinding)
    for action in ("recommend_tools", "compare_tools", "get_tool_details", "submit_answer"):
        assert bindings.authorize(guest, action, {"task": "email_marketing"}) == "public"
    assert bindings.may_deliver(conn, guest) is True
    denied("sign_in_required", bindings.authorize, guest, "save_plan", PLAN)
    denied("sign_in_required", bindings.issue_receipt, conn, guest, "call-1", "save_plan", PLAN, NOW)
    assert conn.execute("SELECT COUNT(*) FROM agent_run").fetchone()[0] == 0


def test_guest_cannot_redeem_a_signed_in_receipt(conn):
    _, token = receipt_for(conn)
    denied("sign_in_required", bindings.redeem, conn, token, GUEST, "save_plan", PLAN, NOW)


def test_unlisted_actions_are_not_allowed_for_anyone(conn):
    run = bindings.bind_run(conn, ALICE, "conv-1", NOW)
    denied("not_allowed", bindings.authorize, run, "run_shell", {})
    denied("not_private", bindings.issue_receipt, conn, run, "call-1", "recommend_tools", {}, NOW)


@pytest.mark.parametrize("result, expected", [
    ({"success": False, "error": {"code": "plan_conflict"}}, ("failed", "plan_conflict")),
    ({"error": "boom"}, ("failed", None)),
    ("tool finished", ("unconfirmed", None)),
    ({}, ("unconfirmed", None)),
    ({"success": True}, ("succeeded", None)),
])
def test_tool_failure_is_never_recorded_as_business_success(conn, result, expected):
    _, token = receipt_for(conn)
    bindings.redeem(conn, token, ALICE, "save_plan", PLAN, NOW)
    assert bindings.record_outcome(conn, token, result) == expected
    stored = conn.execute("SELECT outcome FROM action_receipt").fetchone()[0]
    assert stored == expected[0]


def test_outcome_cannot_be_recorded_before_the_receipt_was_redeemed(conn):
    _, token = receipt_for(conn)
    bindings.record_outcome(conn, token, {"success": True})
    assert conn.execute("SELECT outcome FROM action_receipt").fetchone()[0] is None


def test_a_tool_server_resumes_the_run_with_identity_from_server_rows(conn):
    from app.agent.chat_actions import RunGate
    run = bindings.bind_run(conn, ALICE, "conv-1", NOW)
    gate = RunGate.resume(conn, None, run.run_id, now=lambda: NOW)
    assert gate.binding == run and gate.principal == ALICE
    assert gate.check("save_plan", PLAN) == "private"
    denied("forged_binding", gate.check, "save_plan", dict(PLAN, owner_hash="someone-else"))


def test_resuming_an_unknown_or_logged_out_run_fails(conn):
    from app.agent.chat_actions import RunGate
    run = bindings.bind_run(conn, ALICE, "conv-1", NOW)
    denied("unknown_run", RunGate.resume, conn, None, "not-a-run")
    logout(conn, ALICE)
    denied("session_ended", RunGate.resume, conn, None, run.run_id)


def test_a_resumed_run_shares_one_receipt_per_call_with_the_route(conn):
    from app.agent.chat_actions import RunGate
    run, _ = receipt_for(conn)
    gate = RunGate.resume(conn, None, run.run_id, now=lambda: NOW)
    denied("duplicate_call", bindings.issue_receipt, conn, gate.binding, "call-1", "save_plan", PLAN, NOW)
