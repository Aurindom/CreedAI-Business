import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.comparison import AssignmentError, compare
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


def test_a_shared_task_goes_to_one_tool_when_each_tool_is_needed_elsewhere(catalog):
    add_card(catalog, "jobs", "jobs")
    catalog.tools += [
        tool("front", 40, [cap("phone", plan="Core"), cap("jobs", plan="Core")], entry_plan=fact("Core")),
        tool("back", 30, [cap("jobs", plan="Core"), cap("bookkeeping", plan="Core")], entry_plan=fact("Core")),
    ]
    result = run(catalog, ["calls", "jobs", "books"], ["front", "back"])
    jobs = result.tasks[1]
    assert jobs.assigned_to == "front" and jobs.suggested and jobs.candidate_ids == ["front", "back"]
    assert [t.role for t in result.tools] == ["fills_gap", "fills_gap"]
    assert [line.problem_ids for line in result.stack.lines] == [["calls", "jobs"], ["books"]]
    assert result.stack.total_monthly_usd == 70 and "You can change that" in result.stack_note


def test_the_suggestion_follows_the_lower_added_cost(catalog):
    add_card(catalog, "jobs", "jobs")
    catalog.tools += [
        tool("front", 40, [cap("phone", plan="Core"), cap("jobs", "add_on", 15, plan="Core")], entry_plan=fact("Core")),
        tool("back", 30, [cap("jobs", plan="Core"), cap("bookkeeping", plan="Core")], entry_plan=fact("Core")),
    ]
    result = run(catalog, ["calls", "jobs", "books"], ["front", "back"])
    assert result.tasks[1].assigned_to == "back" and result.stack.total_monthly_usd == 70


def test_the_owner_can_assign_a_task_to_one_of_the_alternatives(catalog):
    result = compare(catalog, HVAC, ["calls"], ["voice", "solo"], {"calls": "solo"})
    assert result.tasks[0].kind == "covered" and not result.tasks[0].suggested
    assert {t.tool_id: t.role for t in result.tools} == {"voice": "not_needed", "solo": "fills_gap"}
    assert result.stack.total_monthly_usd == 60


def test_a_task_cannot_be_assigned_to_a_tool_that_does_not_fit_it(catalog):
    with pytest.raises(AssignmentError):
        compare(catalog, HVAC, ["calls"], ["voice", "foreign"], {"calls": "foreign"})


def test_a_pending_tool_is_only_a_possible_fit(catalog):
    catalog.tools[2] = catalog.tools[2].model_copy(update={"status": "pending_review"})
    profile = BusinessProfile(trade="hvac", budget_monthly_usd=500)
    result = run(catalog, ["calls", "books"], ["voice", "ledger"], profile)
    assert result.tools[0].tasks[0].coverage == "possible" and result.tools[0].role == "might_fill_gap"
    assert [s.kind for s in result.tasks] == ["possible", "covered"]
    stack = result.stack
    assert stack.total_monthly_usd == 130 and not stack.ready and stack.within_budget is None and stack.unconfirmed == ["Voice"]
    assert any("isn't a confirmed total" in a for a in stack.assumptions)


def test_an_unconfirmed_fit_is_not_ready(catalog):
    catalog.tools.append(tool("vague", 25, [cap("phone", plan="Core")], applicability="unknown", entry_plan=fact("Core")))
    result = run(catalog, ["calls", "books"], ["vague", "ledger"], BusinessProfile(trade="hvac", budget_monthly_usd=500))
    assert result.tasks[0].kind == "possible" and not result.stack.ready and result.stack.within_budget is None


def test_an_unknown_price_is_not_ready(catalog):
    stack = run(catalog, ["calls", "books"], ["mystery", "ledger"], BusinessProfile(trade="hvac", budget_monthly_usd=500)).stack
    assert stack.lines[0].confirmed and not stack.ready and stack.within_budget is None


def test_a_set_aside_tool_is_excluded(catalog):
    fits = run(catalog, ["calls"], ["voice", "foreign"]).tools[1].tasks
    assert [f.coverage for f in fits] == ["excluded"]


def test_a_confirmed_tool_is_not_blocked_by_an_uncertain_extra(catalog):
    catalog.tools.append(tool("maybe", 20, [cap("phone", plan="Core")], status="pending_review", entry_plan=fact("Core")))
    result = run(catalog, ["calls"], ["voice", "maybe"])
    assert result.tasks[0].kind == "covered" and result.tasks[0].assigned_to == "voice"
    assert {t.tool_id: t.role for t in result.tools} == {"voice": "fills_gap", "maybe": "not_needed"}
    assert result.stack.ready and result.stack.total_monthly_usd == 100


def _packs(catalog, first_offer, second_offer, second_price=29):
    catalog.tools.append(tool(
        "packs", 50,
        [cap("phone", "add_on", 29, plan="Base", offer=first_offer), cap("bookkeeping", "add_on", second_price, plan="Base", offer=second_offer)],
        entry_plan=fact("Base"),
    ))


OWNER = BusinessProfile(trade="hvac", owned=[OwnedSoftware(tool_id="packs", plan="Base")])


@pytest.mark.parametrize("offers, new_buyer, owner", [(("pack", "pack"), 79, 29), (("voice-pack", "books-pack"), 108, 58)])
def test_each_add_on_offer_is_charged_once(catalog, offers, new_buyer, owner):
    _packs(catalog, *offers)
    assert run(catalog, ["calls", "books"], ["packs"]).stack.total_monthly_usd == new_buyer
    assert run(catalog, ["calls", "books"], ["packs"], OWNER).stack.total_monthly_usd == owner


@pytest.mark.parametrize("profile", [HVAC, OWNER])
def test_add_ons_with_no_recorded_offer_are_not_added_up(catalog, profile):
    _packs(catalog, None, None)
    line = run(catalog, ["calls", "books"], ["packs"], profile).stack.lines[0]
    assert line.monthly_usd is None and "one purchase or separate" in line.note


def test_one_offer_at_two_prices_is_not_guessed(catalog):
    _packs(catalog, "pack", "pack", second_price=35)
    assert run(catalog, ["calls", "books"], ["packs"]).stack.total_monthly_usd is None


def test_an_add_on_offer_needs_an_add_on():
    with pytest.raises(ValidationError):
        cap("phone", offer="pack")


def test_an_all_in_one_tool_is_shown_beside_the_choice_not_swapped_in(catalog):
    catalog.tools.append(tool("combo", 70, [cap("phone", plan="Core"), cap("bookkeeping", plan="Core")], entry_plan=fact("Core")))
    result = run(catalog, ["calls", "books"], ["voice", "ledger"])
    assert [(a.tool_id, a.coverage, a.monthly_usd) for a in result.all_in_one] == [("combo", "confirmed", 70)]
    assert [line.tool_id for line in result.stack.lines] == ["voice", "ledger"] and result.stack.total_monthly_usd == 130
    assert "comparison only" in result.all_in_one_note and "sav" not in result.all_in_one_note.lower()


def test_no_all_in_one_tool_says_a_wider_search_is_needed(catalog):
    result = run(catalog, ["calls", "books"], ["voice", "ledger"])
    assert result.all_in_one == [] and "wider search" in result.all_in_one_note


def test_compare_endpoint_takes_assignments(client):
    response = client.post("/api/compare", json=_body(assignments={"missed_calls": "jobber"}))
    assert response.status_code == 200 and response.json()["tasks"][0]["assigned_to"] == "jobber"


@pytest.mark.parametrize("assignments", [{"missed_calls": "housecall_pro"}, {"nope": "jobber"}])
def test_compare_rejects_assignments_outside_the_selection(client, assignments):
    assert client.post("/api/compare", json=_body(assignments=assignments)).status_code == 422


def test_a_task_nothing_covers_blocks_readiness_but_keeps_the_subtotal(catalog):
    profile = BusinessProfile(trade="hvac", budget_monthly_usd=500)
    stack = run(catalog, ["calls", "books"], ["voice"], profile).stack
    assert stack.total_monthly_usd == 100 and stack.uncovered == ["t"]
    assert not stack.ready and stack.within_budget is None
    assert any("isn't the full cost" in a for a in stack.assumptions)


def test_jobber_receptionist_is_charged_once_for_calls_and_lead_replies(client):
    def stack(problem_ids):
        return client.post("/api/compare", json=_body(problem_ids=problem_ids)).json()["stack"]

    one = stack(["missed_calls"])
    both = stack(["missed_calls", "slow_lead_replies"])
    assert one["total_monthly_usd"] is not None and both["total_monthly_usd"] == one["total_monthly_usd"]
