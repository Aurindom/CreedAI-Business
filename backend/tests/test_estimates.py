from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app import adoption
from app.comparison import compare
from app.facts import tool_facts
from app.matching import recommend
from app.schemas import BusinessProfile, Fact, OwnedSoftware, Selection
from conftest import fact

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)
BUDGET = BusinessProfile(trade="hvac", budget_monthly_usd=500)


def estimate(value):
    return fact(value).model_copy(update={"inferred": True, "note": "Which price is monthly was inferred."})


def with_estimated_price(catalog, tool_id):
    index = next(i for i, t in enumerate(catalog.tools) if t.id == tool_id)
    old = catalog.tools[index]
    catalog.tools[index] = old.model_copy(update={"entry_monthly_usd": estimate(old.entry_monthly_usd.value)})


@pytest.mark.parametrize("fields", [{"status": "present", "value": 49}, {"status": "unknown"}])
def test_an_inferred_fact_needs_a_present_value_and_a_note(fields):
    sourced = {"source_url": "https://example.com/p", "source_type": "vendor", "checked": "2026-11-06"} if fields["status"] == "present" else {}
    with pytest.raises(ValidationError):
        Fact(**fields, **sourced, inferred=True)


def test_an_estimated_price_never_wins_outright(catalog):
    with_estimated_price(catalog, "solo")
    result = recommend(catalog, BUDGET, catalog.problem("calls"))
    assert "solo" not in [o.tool_id for o in result.options] and result.winner_tool_id != "solo"
    top = next(o for o in result.check_first if o.tool_id == "solo")
    assert top.price_estimated and top.added_monthly_usd == 60 and top.status == "pending_review"
    assert top.within_budget is None and "estimate" in top.cost_note


def test_an_estimated_add_on_price_is_not_a_confirmed_add_on(catalog):
    suite = catalog.tools[0]
    phone = suite.capability("phone").model_copy(update={"addon_monthly_usd": estimate(29)})
    catalog.tools[0] = suite.model_copy(update={"capabilities": [phone, suite.capability("jobs")]})
    profile = BusinessProfile(trade="hvac", owned=[OwnedSoftware(tool_id="suite", plan="Base")])
    result = recommend(catalog, profile, catalog.problem("calls"))
    assert result.check_first[0].route == "native_add_on" and result.check_first[0].price_estimated
    assert "suite" not in [o.tool_id for o in result.options]
    assert result.outcome == "verify_with_vendor" and result.winner_tool_id is None


def test_a_stack_with_an_estimated_price_keeps_the_total_but_is_not_ready(catalog):
    with_estimated_price(catalog, "voice")
    result = compare(catalog, BUDGET, ["calls", "books"], ["voice", "ledger"])
    stack = result.stack
    assert stack.total_monthly_usd == 130 and not stack.ready and stack.within_budget is None
    assert stack.estimated == ["Voice"] and [line.price_estimated for line in stack.lines] == [True, False]
    assert any("estimate" in a for a in stack.assumptions) and "Prices to check" in result.stack_note


def test_a_plan_with_an_estimated_price_is_a_draft(catalog):
    with_estimated_price(catalog, "voice")
    selection = Selection(profile={"trade": "hvac"}, problem_ids=["calls", "books"], tool_ids=["voice", "ledger"])
    plan = adoption.build_plan(catalog, selection, "p", NOW)
    assert plan.status == "draft" and any("Voice" in item and "estimate" in item for item in plan.open_items)


def test_the_fact_list_labels_an_estimate(catalog):
    with_estimated_price(catalog, "voice")
    price = tool_facts(next(t for t in catalog.tools if t.id == "voice"))[0]
    assert price.inferred and price.value.endswith("(estimate)") and price.state == "known"


def test_every_inferred_catalog_price_says_what_was_inferred(client):
    for tool in client.get("/api/tools").json():
        for name in ("entry_monthly_usd", "plan_prices"):
            data = tool.get(name) or {}
            if data.get("inferred"):
                assert "inferred" in (data.get("note") or "").lower()


def test_jobber_compare_is_priced_but_waits_on_its_pricing_page(client):
    stack = client.post("/api/compare", json={"profile": {"trade": "hvac"}, "problem_ids": ["missed_calls"], "tool_ids": ["jobber"]}).json()["stack"]
    assert stack["total_monthly_usd"] is not None and stack["estimated"] == ["Jobber"] and not stack["ready"]
