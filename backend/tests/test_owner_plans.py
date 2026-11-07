import pytest

from app.matching import recommend
from app.schemas import BusinessProfile, Fact, OwnedSoftware
from conftest import cap, fact, tool

TIERS = ["Lite", "Pro", "Max"]


def answer(catalog, plan):
    catalog.tools = [tool("crm", 40, [cap("phone", plan="Pro")], entry_plan=fact("Lite"), plan_tiers=fact(TIERS))]
    profile = BusinessProfile(trade="hvac", owned=[OwnedSoftware(tool_id="crm", plan=plan)])
    return recommend(catalog, profile, catalog.problem("calls"))


def test_owners_on_different_tiers_get_different_answers(catalog):
    lite, maxed = answer(catalog, "Lite"), answer(catalog, "Max")
    assert lite.options[0].route == "plan_upgrade" and lite.outcome == "verify_with_vendor"
    assert maxed.options[0].route == "already_have" and maxed.outcome == "no_new_tool"


@pytest.mark.parametrize("plan", [None, "", "  ", "Legacy Gold 2019"])
def test_unknown_or_custom_plan_is_never_a_zero_cost_claim(catalog, plan):
    top = answer(catalog, plan).options[0]
    assert top.route == "check_plan" and top.added_monthly_usd is None


def test_changing_the_plan_recomputes_the_answer(catalog):
    routes = [answer(catalog, p).options[0].route for p in ("Lite", None, "Pro")]
    assert routes == ["plan_upgrade", "check_plan", "already_have"]


def test_plan_label_matches_regardless_of_case_and_spacing(catalog):
    assert answer(catalog, "  pro ").options[0].route == "already_have"


def test_api_accepts_owned_plans_and_old_clients_still_work(client):
    new = {"profile": {"trade": "hvac", "owned": [{"tool_id": "jobber", "plan": "Core"}]}, "problem_id": "missed_calls"}
    old = {"profile": {"trade": "hvac", "owned_tool_ids": ["jobber"]}, "problem_id": "missed_calls"}
    assert client.post("/api/recommend", json=new).status_code == 200
    assert client.post("/api/recommend", json=old).status_code == 200


def test_api_rejects_an_unbounded_plan_label(client):
    body = {"profile": {"owned": [{"tool_id": "jobber", "plan": "x" * 101}]}, "problem_id": "missed_calls"}
    assert client.post("/api/recommend", json=body).status_code == 422


def test_facts_route_matches_the_card_facts(client):
    facts = client.get("/api/tools/mailchimp/facts").json()
    assert [f["label"] for f in facts] == ["Entry price", "Setup", "Privacy", "Support"]
    price = facts[0]
    assert price["state"] == "known" and price["source_url"] and price["checked"]
    result = client.post("/api/recommend", json={"profile": {"owned": [{"tool_id": "mailchimp"}]}, "problem_id": "email_marketing"}).json()
    card = next(o for o in result["options"] if o["tool_id"] == "mailchimp")
    assert card["facts"] == facts


def test_facts_route_unknown_tool_is_a_404(client):
    assert client.get("/api/tools/nope/facts").status_code == 404
