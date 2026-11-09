from datetime import date
from pathlib import Path

import pytest

from app import db
from app.comparison import compare
from app.matching import checked_for, recommend
from app.schemas import AutomaticReview, BusinessProfile, Fact, OwnedSoftware
from conftest import cap, fact, tool

CATALOG = db.load_catalog_file(Path(__file__).resolve().parent.parent / "data" / "catalog.json")


def run(catalog, problem="calls", trade="hvac", owned=None):
    owned = [OwnedSoftware(tool_id=t, plan=p) for t, p in (owned or {}).items()]
    return recommend(catalog, BusinessProfile(trade=trade, owned=owned), catalog.problem(problem))


def assert_confident_lists_are_checked(result):
    assert all(o.status == "verified" for o in result.options)
    assert all(o.tool_id not in {c.tool_id for c in result.check_first} for o in result.options)
    if result.winner_tool_id:
        assert result.winner_tool_id == result.options[0].tool_id
        assert result.options[0].status == "verified"


def sourced(tool_id, price, **extra):
    return tool(tool_id, price, [cap("phone", plan="Core")], entry_plan=fact("Core"), **extra)


def stale(value):
    return Fact(status="present", value=value, source_url="https://example.com/p", source_type="vendor", checked="2026-10-01")


def review(capability, eligible, conflict=False):
    return AutomaticReview(checked=date(2026, 11, 8), capability=capability, checks={}, notes=["Confirm the plan."],
                           sources=["https://example.com/p"], eligible=eligible,
                           evidence={"conflicts": {"plan": "true"}} if conflict else {})


def test_exact_restaurant_staff_scheduling_payload_keeps_unchecked_tools_out_of_options(client):
    body = {"problem_id": "staff_scheduling", "profile": {"trade": "restaurant"}}
    result = client.post("/api/recommend", json=body).json()
    assert result["outcome"] == "new_tool" and result["winner_tool_id"] == "homebase"
    assert [o["tool_id"] for o in result["options"]] == ["homebase"]
    assert all(o["status"] == "verified" for o in result["options"])
    pending = {o["tool_id"]: o["status"] for o in result["check_first"]}
    assert {"seven_shifts", "connecteam"} <= set(pending)
    assert set(pending.values()) == {"pending_review"}


def test_checked_winner_with_pending_alternatives(catalog):
    catalog.tools = [sourced("solo", 60), tool("alt", 30, [cap("phone")], status="pending_review"),
                     tool("other", 20, [cap("phone")])]
    result = run(catalog)
    assert result.winner_tool_id == "solo" and [o.tool_id for o in result.options] == ["solo"]
    assert {o.tool_id for o in result.check_first} == {"alt", "other"}
    assert_confident_lists_are_checked(result)


def test_a_cheaper_unchecked_tool_never_outranks_a_checked_one(catalog):
    catalog.tools = [sourced("solo", 60), tool("cheap", 1, [cap("phone")])]
    result = run(catalog)
    assert result.winner_tool_id == "solo" and result.check_first[0].tool_id == "cheap"


def test_an_expired_scope_is_not_checked(catalog):
    expired = tool("old", 60, [cap("phone", plan="Core")], entry_plan=fact("Core"))
    phone = expired.capabilities[0].model_copy(update={"access": stale("included")})
    expired = expired.model_copy(update={"capabilities": [phone]})
    catalog.tools = [expired]
    result = run(catalog)
    assert result.options == [] and result.check_first[0].tool_id == "old"
    assert result.outcome == "verify_with_vendor" and result.winner_tool_id is None


def test_a_legacy_verified_flag_is_not_approval_for_every_task(catalog):
    legacy = tool("flag", 60, [cap("phone")], status="verified")
    assert not checked_for(legacy, "phone")


def test_approval_for_another_capability_does_not_carry_over(catalog):
    other = sourced("other", 40, origin="discovered", auto_review=review("bookkeeping", True))
    catalog.tools = [other]
    result = run(catalog)
    assert result.options == [] and result.check_first[0].tool_id == "other"


def test_a_positive_scoped_review_counts_for_a_discovered_tool(catalog):
    found = sourced("found", 40, origin="discovered", reviews={"phone": review("phone", True)})
    assert checked_for(found, "phone")


def test_a_conflicting_review_closes_the_scope_even_with_current_curated_facts(catalog):
    conflicted = sourced("conflict", 40, reviews={"phone": review("phone", False, conflict=True)})
    assert not checked_for(conflicted, "phone")


def test_independent_current_curated_facts_still_count(catalog):
    curated = sourced("curated", 40, reviews={"phone": review("phone", False)})
    assert checked_for(curated, "phone")


def test_missing_price_is_checked_first(catalog):
    catalog.tools = [tool("unpriced", None, [cap("phone", plan="Core")], entry_plan=fact("Core"))]
    result = run(catalog)
    assert result.options == [] and result.check_first[0].added_monthly_usd is None


def test_no_checked_options_gives_no_winner(catalog):
    catalog.tools = [tool("a", 10, [cap("phone")]), tool("b", 20, [cap("phone")])]
    result = run(catalog)
    assert result.options == [] and result.winner_tool_id is None and result.outcome == "verify_with_vendor"


def test_an_unchecked_tool_the_owner_has_blocks_a_confident_new_purchase(catalog):
    catalog.tools = [sourced("solo", 60), tool("mine", 40, [cap("phone")])]
    result = run(catalog, owned={"mine": None})
    assert result.options[0].tool_id == "solo" and result.check_first[0].tool_id == "mine"
    assert result.outcome == "verify_with_vendor" and result.winner_tool_id is None
    assert "Mine" in result.message


def test_comparison_only_confirms_scoped_tools(catalog):
    catalog.tools = [sourced("solo", 60), tool("alt", 30, [cap("phone")])]
    fits = {t.tool_id: t.tasks[0].coverage for t in compare(catalog, BusinessProfile(trade="hvac"), ["calls"], ["solo", "alt"]).tools}
    assert fits == {"solo": "confirmed", "alt": "possible"}


@pytest.mark.parametrize("trade", [None, *[t.id for t in CATALOG.trades]])
def test_every_real_task_and_business_keeps_unchecked_tools_out_of_confident_lists(trade):
    for card in CATALOG.problem_cards:
        result = recommend(CATALOG, BusinessProfile(trade=trade), card)
        assert_confident_lists_are_checked(result)
        if result.outcome in {"new_tool", "add_on", "no_new_tool"}:
            assert result.options and result.options[0].status == "verified"


def test_real_catalog_with_an_owned_tool_never_promotes_pending_items():
    for card in CATALOG.problem_cards:
        for owned in {t.id for t in CATALOG.tools if t.capability(card.capability)}:
            result = recommend(CATALOG, BusinessProfile(trade="hvac", owned=[OwnedSoftware(tool_id=owned)]), card)
            assert_confident_lists_are_checked(result)


def test_directory_reports_only_task_scoped_checks(client):
    tools = {t["id"]: t for t in client.get("/api/tools").json()}
    assert "staff_scheduling" in tools["homebase"]["checked_capabilities"]
    assert tools["seven_shifts"]["checked_capabilities"] == []
    assert client.get("/api/tools/homebase").json()["checked_capabilities"] == tools["homebase"]["checked_capabilities"]


def test_comparison_and_plan_items_never_borrow_the_product_flag(client):
    profile = {"trade": "restaurant"}
    body = {"profile": profile, "problem_ids": ["staff_scheduling"], "tool_ids": ["homebase", "seven_shifts"]}
    result = client.post("/api/compare", json=body).json()
    statuses = {t["tool_id"]: t["status"] for t in result["tools"]}
    assert statuses == {"homebase": "verified", "seven_shifts": "pending_review"}
