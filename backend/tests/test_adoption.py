import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import access, adoption, db
from app.schemas import Selection
from conftest import cap, fact, tool

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)
PAIR = Selection(profile={"trade": "hvac"}, problem_ids=["calls", "books"], tool_ids=["voice", "ledger"])


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "plans.db")
    yield connection
    connection.close()


@pytest.fixture
def owner(conn):
    token, _ = access.create_session(conn, NOW)
    return access.owner_for(conn, token, NOW)


def save(conn, catalog, owner, request_id="confirm-0001", selection=PAIR):
    return adoption.save_plan(conn, catalog, owner, request_id, selection, NOW)


def test_plan_carries_the_comparison_prices_and_says_it_is_guidance(catalog):
    plan = adoption.build_plan(catalog, PAIR, "p", NOW)
    assert [(s.tool_id, s.monthly_usd) for s in plan.steps] == [("voice", 100), ("ledger", 30)]
    assert plan.stack.total_monthly_usd == 130 and "Nothing is bought" in plan.note


def test_alternatives_must_be_narrowed_before_a_plan(catalog):
    with pytest.raises(adoption.PlanNotReady, match="Pick one per task"):
        adoption.build_plan(catalog, Selection(problem_ids=["calls"], tool_ids=["voice", "solo"]), "p", NOW)


def test_unknowns_become_things_to_confirm_not_guesses(catalog):
    plan = adoption.build_plan(catalog, Selection(profile={"trade": "hvac"}, problem_ids=["calls", "books"], tool_ids=["mystery", "ledger"]), "p", NOW)
    mystery = plan.steps[0]
    assert mystery.monthly_usd is None and plan.stack.total_monthly_usd is None
    assert any("connect" in c for c in mystery.to_confirm)
    assert any("setup" in c for c in mystery.to_confirm) and mystery.setup.known is False


def test_each_task_gets_something_to_try_in_plain_words(catalog):
    catalog.categories[0].labels = {"phone": "answering calls"}
    step = adoption.build_plan(catalog, PAIR, "p", NOW).steps[0]
    assert step.to_try == ["Before paying, check that it handles answering calls the way your business does it"]


def test_a_repeated_confirm_returns_the_first_plan(conn, catalog, owner):
    first, created = save(conn, catalog, owner)
    again, created_again = save(conn, catalog, owner)
    assert created and not created_again and again.id == first.id
    assert conn.execute("SELECT COUNT(*) FROM adoption_plan").fetchone()[0] == 1


def test_a_reused_confirm_id_for_another_selection_is_refused(conn, catalog, owner):
    save(conn, catalog, owner)
    with pytest.raises(adoption.PlanConflict):
        save(conn, catalog, owner, selection=Selection(profile={"trade": "hvac"}, problem_ids=["calls"], tool_ids=["voice"]))


def test_another_owner_cannot_read_or_list_the_plan(conn, catalog, owner):
    plan, _ = save(conn, catalog, owner)
    token, _ = access.create_session(conn, NOW)
    stranger = access.owner_for(conn, token, NOW)
    with pytest.raises(adoption.PlanNotFound):
        adoption.load_plan(conn, stranger, plan.id)
    assert adoption.list_plans(conn, stranger) == [] and len(adoption.list_plans(conn, owner)) == 1


def test_a_price_change_does_not_rewrite_the_saved_estimate(conn, catalog, owner):
    plan, _ = save(conn, catalog, owner)
    catalog.tools[2] = tool("voice", 120, [cap("phone", plan="Core")], connects=["ledger"], entry_plan=fact("Core"))
    saved = adoption.check_plan(catalog, adoption.load_plan(conn, owner, plan.id))
    assert saved.changed and saved.plan.stack.total_monthly_usd == 130 and saved.current_total_monthly_usd == 150
    later = NOW + timedelta(days=1)
    refreshed = adoption.refresh_plan(conn, catalog, owner, plan.id, later)
    assert refreshed.stack.total_monthly_usd == 150 and refreshed.created_at == NOW and refreshed.refreshed_at == later
    assert not adoption.check_plan(catalog, adoption.load_plan(conn, owner, plan.id)).changed


def test_a_plan_whose_tool_left_the_catalog_says_so(conn, catalog, owner):
    plan, _ = save(conn, catalog, owner)
    catalog.tools = [t for t in catalog.tools if t.id != "voice"]
    saved = adoption.check_plan(catalog, adoption.load_plan(conn, owner, plan.id))
    assert saved.changed and "can't be rebuilt" in saved.change_note and saved.plan.stack.total_monthly_usd == 130


def test_plans_per_session_are_capped(conn, catalog, owner, monkeypatch):
    monkeypatch.setattr(adoption, "MAX_PLANS", 1)
    save(conn, catalog, owner)
    with pytest.raises(adoption.PlanLimit):
        save(conn, catalog, owner, request_id="confirm-0002")


def test_only_a_hash_of_the_token_is_stored(conn):
    token, _ = access.create_session(conn, NOW)
    stored = [row[0] for row in conn.execute("SELECT token_hash FROM owner_session")]
    assert token not in stored and access.token_hash(token) in stored


@pytest.mark.parametrize("ending", ["expired", "revoked", "unknown", "missing"])
def test_ended_sessions_are_refused(conn, ending):
    token, expires = access.create_session(conn, NOW)
    when = expires if ending == "expired" else NOW
    if ending == "revoked":
        access.revoke(conn, access.token_hash(token), NOW)
    given = {"unknown": "not-a-real-token", "missing": None}.get(ending, token)
    with pytest.raises(access.AccessDenied):
        access.owner_for(conn, given, when)


@pytest.mark.parametrize("header, expected", [("Bearer abc", "abc"), ("bearer  abc ", "abc"), ("Basic abc", None), ("Bearer ", None), (None, None)])
def test_bearer_header_parsing(header, expected):
    assert access.bearer(header) == expected


BODY = {"profile": {"trade": "hvac"}, "problem_ids": ["missed_calls"], "tool_ids": ["jobber"], "request_id": "confirm-0001"}


def start(client):
    response = client.post("/api/sessions")
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_private_routes_need_a_live_session(client):
    assert client.get("/api/plans").status_code == 401
    response = client.get("/api/plans", headers={"Authorization": "Bearer secret-guess-123"})
    assert response.status_code == 401 and "secret-guess-123" not in response.text


def test_save_repeat_read_and_list(client):
    auth = start(client)
    first = client.post("/api/plans", json=BODY, headers=auth)
    repeat = client.post("/api/plans", json=BODY, headers=auth)
    assert (first.status_code, repeat.status_code) == (201, 200) and first.json()["id"] == repeat.json()["id"]
    read = client.get(f"/api/plans/{first.json()['id']}", headers=auth)
    assert read.status_code == 200 and read.json()["changed"] is False
    assert [p["id"] for p in client.get("/api/plans", headers=auth).json()] == [first.json()["id"]]


def test_owner_b_cannot_reach_owner_a_by_changing_the_id(client):
    plan_id = client.post("/api/plans", json=BODY, headers=start(client)).json()["id"]
    other = start(client)
    assert client.get(f"/api/plans/{plan_id}", headers=other).status_code == 404
    assert client.post(f"/api/plans/{plan_id}/refresh", headers=other).status_code == 404


def test_a_closed_session_stops_working(client):
    auth = start(client)
    assert client.delete("/api/sessions/current", headers=auth).status_code == 204
    assert client.get("/api/plans", headers=auth).status_code == 401


def test_saved_plans_survive_a_restart(client):
    from app.main import app

    auth = start(client)
    plan_id = client.post("/api/plans", json=BODY, headers=auth).json()["id"]
    with TestClient(app) as restarted:
        assert restarted.get(f"/api/plans/{plan_id}", headers=auth).status_code == 200


def test_private_writes_can_be_turned_off(client, monkeypatch):
    monkeypatch.setenv("PRIVATE_PLANS", "off")
    assert client.post("/api/sessions").status_code == 503
    assert client.post("/api/plans", json=BODY, headers={"Authorization": "Bearer x"}).status_code == 503


@pytest.mark.parametrize("change, status", [
    ({"request_id": "short"}, 422),
    ({"tool_ids": ["jobber", "jobber"]}, 422),
    ({"tool_ids": ["nope"]}, 404),
    ({"tool_ids": ["jobber", "housecall_pro"]}, 409),
])
def test_bad_plan_requests(client, change, status):
    assert client.post("/api/plans", json={**BODY, **change}, headers=start(client)).status_code == status


def test_a_fully_confirmed_plan_is_checked(catalog):
    plan = adoption.build_plan(catalog, PAIR, "p", NOW)
    assert plan.status == "checked" and plan.open_items == [] and [s.coverage for s in plan.steps] == ["confirmed", "confirmed"]


def test_a_plan_with_an_unknown_price_is_a_draft(catalog):
    plan = adoption.build_plan(catalog, Selection(profile={"trade": "hvac"}, problem_ids=["calls", "books"], tool_ids=["mystery", "ledger"]), "p", NOW)
    assert plan.status == "draft" and any("Mystery" in item for item in plan.open_items)


def test_a_plan_with_a_pending_tool_is_a_draft_that_says_what_to_check(catalog):
    catalog.tools[2] = catalog.tools[2].model_copy(update={"status": "pending_review"})
    plan = adoption.build_plan(catalog, PAIR, "p", NOW)
    assert plan.status == "draft" and plan.steps[0].coverage == "possible"
    assert any("Voice" in item for item in plan.open_items) and any("rechecked" in c for c in plan.steps[0].to_confirm)


def test_an_assigned_alternative_becomes_a_plan(catalog):
    selection = Selection(problem_ids=["calls"], tool_ids=["voice", "solo"], assignments={"calls": "solo"})
    plan = adoption.build_plan(catalog, selection, "p", NOW)
    assert [s.tool_id for s in plan.steps] == ["solo"] and plan.stack.total_monthly_usd == 60


def test_a_plan_saved_before_this_change_still_loads_and_offers_a_refresh(conn, catalog, owner):
    plan, _ = save(conn, catalog, owner)
    old = plan.model_dump(mode="json", exclude={"status", "open_items"})
    for step in old["steps"]:
        step.pop("coverage")
    for key in ("ready", "unconfirmed"):
        old["stack"].pop(key)
    for line in old["stack"]["lines"]:
        line.pop("confirmed")
    old["selection"].pop("assignments")
    with conn:
        conn.execute("UPDATE adoption_plan SET doc = ? WHERE id = ?", (json.dumps(old), plan.id))
    loaded = adoption.load_plan(conn, owner, plan.id)
    assert loaded.status == "legacy"
    saved = adoption.check_plan(catalog, loaded)
    assert saved.changed and saved.plan.stack.total_monthly_usd == 130
    assert adoption.refresh_plan(conn, catalog, owner, plan.id, NOW).status == "checked"


def test_the_request_hash_ignores_empty_assignments():
    assert "assignments" not in Selection(problem_ids=["calls"], tool_ids=["voice"]).model_dump_json(exclude={"assignments"})
    plain = adoption._request_hash(Selection(problem_ids=["calls"], tool_ids=["voice"]))
    legacy = hashlib.sha256(json.dumps({"profile": Selection(problem_ids=["calls"], tool_ids=["voice"]).profile.model_dump(mode="json"), "problem_ids": ["calls"], "tool_ids": ["voice"]}, separators=(",", ":")).encode("utf-8")).hexdigest()
    assigned = adoption._request_hash(Selection(problem_ids=["calls"], tool_ids=["voice"], assignments={"calls": "voice"}))
    assert plain == legacy and assigned != plain


def test_a_bad_assignment_on_save_is_refused(client):
    body = {**BODY, "tool_ids": ["jobber", "housecall_pro"], "assignments": {"missed_calls": "nope"}}
    assert client.post("/api/plans", json=body, headers=start(client)).status_code == 422
