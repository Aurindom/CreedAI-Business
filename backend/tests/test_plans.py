from app.matching import recommend
from app.facts import tool_facts
from app.schemas import BusinessProfile, OwnedSoftware
from conftest import cap, fact, tool


def owner_result(catalog, owned_tool, plan=None):
    catalog.tools = [owned_tool, tool("solo", 60, [cap("phone")])]
    profile = BusinessProfile(trade="hvac", owned=[OwnedSoftware(tool_id=owned_tool.id, plan=plan)])
    return recommend(catalog, profile, catalog.problem("calls"))


def tiered(**cap_args):
    return tool("crm", 40, [cap("phone", **cap_args)], entry_plan=fact("Lite"), plan_tiers=fact(["Lite", "Pro", "Max"]))


def test_unknown_access_is_check_your_plan_not_a_paid_add_on(catalog):
    result = owner_result(catalog, tool("crm", 40, [cap("phone", "unknown")]))
    top = result.options[0]
    assert top.route == "check_plan" and top.added_monthly_usd is None
    assert result.outcome == "verify_with_vendor" and result.winner_tool_id is None
    assert "Check your plan" in top.cost_note


def test_included_without_a_plan_fact_is_not_claimed_as_owned(catalog):
    top = owner_result(catalog, tool("crm", 40, [cap("phone")])).options[0]
    assert top.route == "check_plan"
    assert "not on which plans" in top.cost_note


def test_included_on_entry_plan_means_every_owner_has_it(catalog):
    result = owner_result(catalog, tiered(plan="Lite"))
    assert result.outcome == "no_new_tool" and result.options[0].added_monthly_usd == 0


def test_owner_plan_at_or_above_the_tier_has_it(catalog):
    assert owner_result(catalog, tiered(plan="Pro"), plan="max").outcome == "no_new_tool"


def test_owner_plan_below_the_tier_needs_an_upgrade(catalog):
    result = owner_result(catalog, tiered(plan="Pro"), plan="Lite")
    top = result.options[0]
    assert top.route == "plan_upgrade" and top.added_monthly_usd is None
    assert "starts on the Pro plan" in top.cost_note
    assert result.outcome == "verify_with_vendor"


def test_owner_with_unknown_plan_is_told_which_tier_to_check(catalog):
    top = owner_result(catalog, tiered(plan="Pro")).options[0]
    assert top.route == "check_plan"
    assert "Included from the Pro plan" in top.cost_note


def test_known_included_upgrade_and_unknown_plans_give_different_answers(catalog):
    routes = [owner_result(catalog, tiered(plan="Pro"), plan=p).options[0].route for p in ("Max", "Lite", None)]
    assert routes == ["already_have", "plan_upgrade", "check_plan"]


def test_old_profile_shape_still_works():
    profile = BusinessProfile(owned_tool_ids=["a"], owned=[OwnedSoftware(tool_id="b", plan="Pro")])
    assert profile.owned_tool_ids == ["b", "a"]
    assert profile.plan_for("b") == "Pro" and profile.plan_for("a") is None


def test_annual_billing_is_shown_on_the_price():
    t = tool("t", 20, entry_plan=fact("Core"), entry_billing=fact("annual"))
    assert tool_facts(t)[0].value == "$20/mo, Core plan, billed annually"
