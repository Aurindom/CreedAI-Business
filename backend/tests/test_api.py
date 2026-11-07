from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.schemas import Catalog

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog.json"


def test_real_catalog_loads_and_covers_every_problem():
    catalog = db.load_catalog_file(CATALOG_PATH)
    for group in (catalog.tools, catalog.trades, catalog.categories, catalog.problem_cards, catalog.facets):
        ids = [item.id for item in group]
        assert len(ids) == len(set(ids))
    trade_ids = {t.id for t in catalog.trades} | {"all"}
    assert all(set(t.trades) <= trade_ids for t in catalog.tools)
    assert all(set(c.trades) <= trade_ids for c in catalog.problem_cards)
    for card in catalog.problem_cards:
        assert any(t.capability(card.capability) for t in catalog.tools), card.id


def confirms(tool, card):
    """A tool counts for a card only when it has the capability and a sourced fact for every split the card needs."""
    cap = tool.capability(card.capability)
    return cap is not None and all(cap.facets.get(f) and cap.facets[f].known and v in cap.facets[f].value for f, v in card.requires.items())


def test_original_trades_have_an_eligible_tool_for_their_problems():
    catalog = db.load_catalog_file(CATALOG_PATH)
    for card in catalog.problem_cards:
        for trade in ("restaurant", "coffee_shop", "hvac", "landscaping"):
            if card.common_for(trade):
                assert any(confirms(t, card) and t.fit(trade) in ("made_for", "any_business") for t in catalog.tools), (card.id, trade)


def test_catalog_goes_beyond_the_first_four_business_types():
    catalog = db.load_catalog_file(CATALOG_PATH)
    assert len(catalog.trades) >= 15
    assert {"bakery", "retail", "salon", "plumbing"} <= {t.id for t in catalog.trades}


def test_categories_cover_every_problem(client):
    categories = client.get("/api/categories").json()
    assert categories and len({c["id"] for c in categories}) == len(categories)
    total = sum(len(client.get("/api/problems", params={"category": c["id"]}).json()) for c in categories)
    assert total == len(client.get("/api/problems").json()) > 0


def test_category_tab_lists_tools_whatever_the_business(client):
    ids = [t["id"] for t in client.get("/api/tools", params={"category": "staff", "trade": "bakery"}).json()]
    assert ids[0] == "homebase"
    assert "seven_shifts" in ids


def test_unknown_category_is_a_404(client):
    assert client.get("/api/tools", params={"category": "nope"}).status_code == 404


def test_field_service_tool_never_wins_for_a_bakery(client):
    result = client.post("/api/recommend", json={"profile": {"trade": "bakery"}, "problem_id": "missed_calls"}).json()
    assert "jobber" not in [o["tool_id"] for o in result["options"]]
    assert result["winner_tool_id"] != "jobber"
    assert any(s["tool_id"] == "jobber" for s in result["set_aside"])


def test_connections_point_only_at_catalog_tools():
    catalog = db.load_catalog_file(CATALOG_PATH)
    ids = {t.id for t in catalog.tools}
    for tool in catalog.tools:
        if tool.connects_to.known:
            assert set(tool.connects_to.value) <= ids, tool.id


def test_catalog_survives_the_database_round_trip(tmp_path):
    catalog = db.load_catalog_file(CATALOG_PATH)
    conn = db.connect(tmp_path / "round.db")
    db.seed(conn, catalog)
    stored = db.read_catalog(conn)
    conn.close()
    assert isinstance(stored, Catalog)
    assert {t.id: t for t in stored.tools} == {t.id: t for t in catalog.tools}


def test_missing_catalog_fails_at_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CATALOG_PATH", str(tmp_path / "absent.json"))
    with pytest.raises(FileNotFoundError):
        with TestClient(app):
            pass
    assert not (tmp_path / "test.db").exists()


def test_problems_list_the_trades_own_first(client):
    ids = [card["id"] for card in client.get("/api/problems", params={"trade": "coffee_shop"}).json()]
    assert ids.index("staff_scheduling") < ids.index("job_scheduling")


def test_unlisted_business_sees_every_problem(client):
    response = client.get("/api/problems", params={"trade": "Pet grooming"})
    assert response.status_code == 200
    assert len(response.json()) == len(client.get("/api/problems").json()) > 0


def test_unlisted_business_browses_all_tools(client):
    response = client.get("/api/tools", params={"trade": "bakery", "capability": "bookkeeping"})
    assert [tool["id"] for tool in response.json()] == ["quickbooks_online"]


def test_bakery_gets_a_general_tool_labeled_as_such(client):
    body = {"profile": {"trade": "Bakery"}, "problem_id": "bookkeeping"}
    result = client.post("/api/recommend", json=body).json()
    assert result["options"][0]["tool_id"] == "quickbooks_online"
    assert result["options"][0]["fit"] == "any_business"
    assert result["tailored"] is False


def test_unlisted_business_is_named_in_the_note(client):
    body = {"profile": {"trade": "Pet grooming"}, "problem_id": "bookkeeping"}
    result = client.post("/api/recommend", json=body).json()
    assert result["winner_tool_id"] == "quickbooks_online"
    assert "Pet grooming" in result["tailoring_note"]


def test_business_type_can_be_left_out(client):
    response = client.post("/api/recommend", json={"profile": {}, "problem_id": "invoicing"})
    assert response.status_code == 200
    assert response.json()["options"]
    assert response.json()["tailored"] is False


def test_listed_trade_matches_however_it_is_typed(client):
    body = {"profile": {"trade": " Coffee Shop "}, "problem_id": "staff_scheduling"}
    result = client.post("/api/recommend", json=body).json()
    assert result["tailored"] is True
    assert result["tailoring_note"] is None


def test_tool_detail_keeps_source_and_date(client):
    price = client.get("/api/tools/jobber").json()["entry_monthly_usd"]
    assert price["source_url"].startswith("https://www.getjobber.com")
    assert price["checked"] == "2026-11-06"


def test_unknown_tool_is_a_404(client):
    assert client.get("/api/tools/nope").status_code == 404


def test_jobber_add_on_waits_until_its_plans_are_sourced(client):
    body = {"profile": {"trade": "hvac", "owned_tool_ids": ["jobber"], "budget_monthly_usd": 100}, "problem_id": "missed_calls"}
    result = client.post("/api/recommend", json=body).json()
    top = result["options"][0]
    assert top["tool_id"] == "jobber" and top["route"] == "native_add_on"
    assert top["added_monthly_usd"] is None
    assert "$29/mo" in top["cost_note"] and "which plans can add it" in top["cost_note"]
    assert result["outcome"] == "verify_with_vendor"


def test_restaurant_missed_calls_has_no_confident_winner(client):
    body = {"profile": {"trade": "restaurant"}, "problem_id": "missed_calls"}
    result = client.post("/api/recommend", json=body).json()
    assert result["outcome"] == "verify_with_vendor"
    assert result["winner_tool_id"] is None


def test_recommend_rejects_a_tool_outside_the_catalog(client):
    body = {"profile": {"trade": "hvac", "owned_tool_ids": ["nope"]}, "problem_id": "missed_calls"}
    assert client.post("/api/recommend", json=body).status_code == 404


def test_negative_budget_is_rejected(client):
    body = {"profile": {"trade": "hvac", "budget_monthly_usd": -1}, "problem_id": "missed_calls"}
    assert client.post("/api/recommend", json=body).status_code == 422


def test_stack_check_reports_duplicates_and_cost(client):
    result = client.post("/api/stack/check", json={"tool_ids": ["jobber", "housecall_pro"]}).json()
    assert result["total_monthly_usd"] == 128
    assert len(result["duplicates"]) == 2
