import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.comparison import compare
from app.matching import recommend
from app.schemas import BusinessProfile, Catalog, Category, OwnedSoftware, ProblemCard
from conftest import cap, fact, tool

HVAC = BusinessProfile(trade="hvac")


def run(catalog, problems, tools, profile=HVAC):
    return compare(catalog, profile, problems, tools)


def card_price(catalog, profile, problem_id, tool_id):
    rec = recommend(catalog, profile, catalog.problem(problem_id))
    return next(o.added_monthly_usd for o in rec.options + rec.check_first if o.tool_id == tool_id)


def add_card(catalog, card_id, capability):
    catalog.problem_cards.append(ProblemCard(id=card_id, title=card_id.title(), plain_words="w", capability=capability, trades=["hvac"]))


def test_two_tools_for_one_task_are_alternatives_not_a_bundle(catalog):
    result = run(catalog, ["calls"], ["voice", "solo"])
    assert result.tasks[0].kind == "alternatives"
    assert [t.role for t in result.tools] == ["alternative", "alternative"]
    assert result.stack is None and "aren't added up" in result.stack_note


def test_complementary_tools_each_fill_a_gap_and_add_up(catalog):
    result = run(catalog, ["calls", "books"], ["voice", "ledger"])
    assert [t.role for t in result.tools] == ["fills_gap", "fills_gap"]
    assert [s.kind for s in result.tasks] == ["covered", "covered"]
    assert result.stack.total_monthly_usd == 130 and result.stack.unknown_cost_tools == []


@pytest.mark.parametrize("profile", [HVAC, BusinessProfile(trade="hvac", owned=[OwnedSoftware(tool_id="suite", plan="Base")])])
def test_comparison_uses_the_same_price_as_the_cards(catalog, profile):
    result = run(catalog, ["calls"], ["suite", "voice", "solo"], profile)
    for compared in result.tools:
        assert compared.tasks[0].added_monthly_usd == card_price(catalog, profile, "calls", compared.tool_id)


def test_one_needed_tool_is_enough(catalog):
    result = run(catalog, ["calls"], ["voice"])
    assert result.tools[0].role == "fills_gap" and result.stack.total_monthly_usd == 100


def test_unknown_price_is_not_counted_as_zero(catalog):
    stack = run(catalog, ["calls", "books"], ["mystery", "ledger"]).stack
    assert stack.total_monthly_usd is None
    assert stack.known_monthly_usd == 30 and stack.unknown_cost_tools == ["Mystery"]


def test_a_shared_add_on_is_charged_once(catalog):
    add_card(catalog, "calls_again", "phone")
    line = run(catalog, ["calls", "calls_again"], ["suite"]).stack.lines[0]
    assert line.monthly_usd == 79 and line.problem_ids == ["calls", "calls_again"]


def test_a_new_buyer_pays_one_plan_that_covers_every_task(catalog):
    add_card(catalog, "jobs", "jobs")
    catalog.tools.append(tool("tiers", 20, [cap("phone", plan="Pro"), cap("jobs", plan="Lite")], entry_plan=fact("Lite"), plan_tiers=fact(["Lite", "Pro"]), plan_prices=fact({"Pro": 40})))
    line = run(catalog, ["calls", "jobs"], ["tiers"]).stack.lines[0]
    assert line.monthly_usd == 40 and "Pro plan" in line.note


def test_plans_with_no_known_order_are_not_guessed(catalog):
    add_card(catalog, "jobs", "jobs")
    catalog.tools.append(tool("loose", 20, [cap("phone", plan="Gold"), cap("jobs", plan="Silver")], entry_plan=fact("Silver")))
    line = run(catalog, ["calls", "jobs"], ["loose"]).stack.lines[0]
    assert line.monthly_usd is None and "order isn't recorded" in line.note


def test_an_owned_tool_adds_only_what_is_missing(catalog):
    add_card(catalog, "jobs", "jobs")
    profile = BusinessProfile(trade="hvac", owned=[OwnedSoftware(tool_id="suite", plan="Base")])
    line = run(catalog, ["calls", "jobs"], ["suite"], profile).stack.lines[0]
    assert line.monthly_usd == 29


def test_connections_need_a_vendor_listing(catalog):
    listed, unlisted = run(catalog, ["calls", "books"], ["voice", "ledger"]).connections[0], run(catalog, ["calls"], ["voice", "solo"]).connections[0]
    assert listed.state == "listed" and listed.listed_by == ["voice"] and "which way" in listed.note
    assert unlisted.state == "unverified" and unlisted.sources == []


def test_owned_tools_are_checked_for_connections(catalog):
    profile = BusinessProfile(trade="hvac", owned=[OwnedSoftware(tool_id="ledger")])
    pairs = [c.tool_ids for c in run(catalog, ["calls"], ["voice"], profile).connections]
    assert pairs == [["voice", "ledger"]]


def test_overlap_uses_plain_labels_and_is_not_called_the_same_job(catalog):
    catalog.categories[0].labels = {"phone": "answering calls"}
    overlap = run(catalog, ["calls"], ["voice", "solo"]).overlaps[0]
    assert "answering calls" in overlap and "doesn't prove" in overlap and "phone" not in overlap


def test_tools_that_do_not_fit_stay_out_of_the_stack(catalog):
    result = run(catalog, ["calls"], ["voice", "foreign", "banned"])
    roles = {t.tool_id: t.role for t in result.tools}
    assert roles == {"voice": "fills_gap", "foreign": "no_fit", "banned": "no_fit"}
    assert [line.tool_id for line in result.stack.lines] == ["voice"]


def test_a_tool_listing_none_of_the_tasks_says_so(catalog):
    compared = run(catalog, ["books"], ["voice", "ledger"]).tools[0]
    assert compared.role == "no_fit" and compared.tasks == [] and "doesn't list" in compared.role_note


def test_an_uncovered_task_is_reported_as_a_gap(catalog):
    result = run(catalog, ["calls", "books"], ["voice"])
    assert result.tasks[1].kind == "gap" and "Nothing chosen covers" in result.stack_note


def test_an_unconfirmed_fit_is_a_research_candidate(catalog):
    catalog.tools.append(tool("vague", 25, [cap("phone", plan="Core")], applicability="unknown", entry_plan=fact("Core")))
    result = run(catalog, ["calls", "books"], ["vague", "ledger"])
    assert result.tools[0].tasks[0].standing == "check_first"
    assert any("Vague still needs checking" in a for a in result.stack.assumptions)


@pytest.mark.parametrize("budget, fits", [(200, True), (100, False)])
def test_stack_total_is_compared_with_the_budget(catalog, budget, fits):
    profile = BusinessProfile(trade="hvac", budget_monthly_usd=budget)
    assert run(catalog, ["calls", "books"], ["voice", "ledger"], profile).stack.within_budget is fits


def test_labels_must_name_held_capabilities():
    with pytest.raises(ValidationError):
        Category(id="c", name="C", capabilities=["a"], labels={"b": "bee"})


def test_every_real_capability_has_a_plain_label():
    catalog = Catalog(**json.loads((Path(__file__).resolve().parent.parent / "data" / "catalog.json").read_text(encoding="utf-8")))
    for category in catalog.categories:
        assert set(category.labels) == set(category.capabilities)


def _body(**extra):
    return {"profile": {"trade": "hvac"}, "problem_ids": ["missed_calls"], "tool_ids": ["jobber"], **extra}


def test_compare_endpoint_answers(client):
    response = client.post("/api/compare", json=_body())
    assert response.status_code == 200 and response.json()["problem_ids"] == ["missed_calls"]


@pytest.mark.parametrize("extra", [
    {"tool_ids": ["jobber", "jobber"]},
    {"problem_ids": ["missed_calls", "missed_calls"]},
    {"tool_ids": []},
    {"tool_ids": ["a", "b", "c", "d"]},
])
def test_compare_rejects_bad_selections(client, extra):
    assert client.post("/api/compare", json=_body(**extra)).status_code == 422


@pytest.mark.parametrize("extra", [{"tool_ids": ["nope"]}, {"problem_ids": ["nope"]}])
def test_compare_unknown_ids_are_not_found(client, extra):
    assert client.post("/api/compare", json=_body(**extra)).status_code == 404
