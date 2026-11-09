import pytest
from pydantic import ValidationError

from app.matching import recommend
from app.schemas import BusinessProfile, Capability, OwnedSoftware
from conftest import cap, fact, tool

TIERS = ["Lite", "Pro", "Max"]


def buyer_option(catalog, candidate):
    catalog.tools = [candidate]
    result = recommend(catalog, BusinessProfile(trade="hvac"), catalog.problem("calls"))
    return result, (result.options + result.check_first)[0]


def owner_option(catalog, owned, plan=None):
    catalog.tools = [owned]
    profile = BusinessProfile(trade="hvac", owned=[OwnedSoftware(tool_id=owned.id, plan=plan)])
    result = recommend(catalog, profile, catalog.problem("calls"))
    return result, (result.options + result.check_first)[0]


def tiered(phone_cap, prices=None, **extra):
    fields = {"entry_plan": fact("Lite"), "plan_tiers": fact(TIERS), **extra}
    if prices is not None:
        fields["plan_prices"] = fact(prices)
    return tool("crm", 40, [phone_cap], **fields)


def test_higher_plan_feature_is_never_priced_at_the_entry_tier(catalog):
    result, top = buyer_option(catalog, tiered(cap("phone", plan="Pro")))
    assert top.added_monthly_usd is None
    assert "Pro plan" in top.cost_note
    assert result.winner_tool_id is None


def test_higher_plan_feature_uses_that_plans_sourced_price(catalog):
    result, top = buyer_option(catalog, tiered(cap("phone", plan="Pro"), prices={"Lite": 40, "Pro": 90, "Max": 200}))
    assert top.added_monthly_usd == 90
    assert top.cost_note.startswith("Pro plan")
    assert result.winner_tool_id == "crm"


def test_entry_plan_feature_uses_the_entry_price(catalog):
    _, top = buyer_option(catalog, tiered(cap("phone", plan="Lite")))
    assert top.added_monthly_usd == 40


def test_included_with_no_plan_fact_abstains_for_a_new_buyer(catalog):
    result, top = buyer_option(catalog, tool("crm", 40, [cap("phone")], entry_plan=fact("Lite")))
    assert top.added_monthly_usd is None
    assert "which plan includes this" in top.cost_note
    assert result.outcome == "verify_with_vendor"


def test_add_on_needing_a_higher_plan_adds_that_plans_price(catalog):
    _, top = buyer_option(catalog, tiered(cap("phone", "add_on", 15, plan="Pro"), prices={"Pro": 90}))
    assert top.added_monthly_usd == 105
    assert "plus the add-on" in top.cost_note


def test_add_on_with_unsourced_prerequisite_never_becomes_a_known_total(catalog):
    _, top = buyer_option(catalog, tiered(cap("phone", "add_on", 15)))
    assert top.added_monthly_usd is None
    assert "which plans can add this" in top.cost_note


def test_owner_add_on_with_unsourced_prerequisite_shows_price_but_no_total(catalog):
    result, top = owner_option(catalog, tiered(cap("phone", "add_on", 15)), plan="Lite")
    assert top.route == "native_add_on" and top.added_monthly_usd is None
    assert "$15/mo" in top.cost_note
    assert result.outcome == "verify_with_vendor"


def test_owner_below_the_add_on_plan_needs_an_upgrade(catalog):
    _, top = owner_option(catalog, tiered(cap("phone", "add_on", 15, plan="Pro")), plan="Lite")
    assert top.route == "plan_upgrade" and top.added_monthly_usd is None
    assert "add-on needs the Pro plan" in top.cost_note


def test_owner_on_the_add_on_plan_gets_the_add_on(catalog):
    sourced = tiered(cap("phone", "add_on", 15, plan="Pro"), prices={"Lite": 40, "Pro": 90, "Max": 200})
    result, top = owner_option(catalog, sourced, plan="Max")
    assert top.route == "native_add_on" and top.added_monthly_usd == 15
    assert result.outcome == "add_on"


def test_owner_add_on_with_an_unpriced_prerequisite_plan_is_checked_first(catalog):
    result, top = owner_option(catalog, tiered(cap("phone", "add_on", 15, plan="Pro")), plan="Max")
    assert result.options == [] and top.route == "native_add_on" and top.status == "pending_review"
    assert result.outcome == "verify_with_vendor" and result.winner_tool_id is None


def test_owner_with_unknown_plan_and_higher_add_on_plan_checks_plan(catalog):
    _, top = owner_option(catalog, tiered(cap("phone", "add_on", 15, plan="Pro")))
    assert top.route == "check_plan"
    assert "add-on from the Pro plan" in top.cost_note


def test_unknown_or_legacy_owner_plan_abstains(catalog):
    _, top = owner_option(catalog, tiered(cap("phone", plan="Pro")), plan="Gold 2019")
    assert top.route == "check_plan" and top.added_monthly_usd is None


def test_sourced_single_offering_skips_the_plan_warning(catalog):
    single = tool("gbp", 0, [cap("phone")], offering=fact("single"))
    result, top = owner_option(catalog, single)
    assert top.route == "already_have"
    assert result.outcome == "no_new_tool"
    _, bought = buyer_option(catalog, single)
    assert bought.added_monthly_usd == 0
    assert "only offering" in bought.cost_note


def test_free_tool_without_a_sourced_offering_still_says_check_plan(catalog):
    _, top = owner_option(catalog, tool("gbp", 0, [cap("phone")]))
    assert top.route == "check_plan"


def test_annual_billing_stays_visible_in_the_cost_note(catalog):
    _, top = buyer_option(catalog, tiered(cap("phone", plan="Lite"), entry_billing=fact("annual")))
    assert "billed annually" in top.cost_note


@pytest.mark.parametrize("fields", [
    {"plan_prices": fact({"Lite": 40})},
    {"plan_tiers": fact(TIERS), "plan_prices": fact({"Ultra": 40})},
    {"plan_tiers": fact(TIERS), "plan_prices": fact({"Pro": -1})},
    {"plan_tiers": fact(TIERS), "plan_prices": fact({"Pro": True})},
    {"offering": fact("single"), "plan_tiers": fact(TIERS)},
    {"offering": fact("bundle")},
])
def test_bad_plan_facts_are_rejected(fields):
    with pytest.raises(ValidationError):
        tool("crm", 40, [], **fields)


def test_add_on_plan_on_an_included_feature_is_rejected():
    with pytest.raises(ValidationError):
        Capability(capability="phone", access=fact("included"), addon_from=fact("Pro"))
