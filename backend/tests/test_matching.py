from app.matching import check_stack, recommend
from app.schemas import BusinessProfile
from conftest import cap, tool


def run(catalog, problem="calls", owned=(), budget=200, trade="hvac"):
    profile = BusinessProfile(trade=trade, owned_tool_ids=list(owned), budget_monthly_usd=budget)
    return recommend(catalog, profile, catalog.problem(problem))


def test_owned_tool_that_includes_it_means_no_new_tool(catalog):
    result = run(catalog, owned=["voice"])
    assert result.outcome == "no_new_tool"
    assert result.winner_tool_id == "voice"
    assert result.options[0].added_monthly_usd == 0


def test_add_on_beats_buying_something_new(catalog):
    result = run(catalog, owned=["suite"])
    assert result.outcome == "add_on"
    assert result.options[0].added_monthly_usd == 29


def test_unknown_add_on_price_has_no_winner(catalog):
    result = run(catalog, owned=["hidden"])
    assert result.outcome == "verify_with_vendor"
    assert result.winner_tool_id is None
    assert result.options[0].added_monthly_usd is None


def test_connected_tool_ranks_above_unconnected(catalog):
    result = run(catalog, owned=["ledger"])
    assert result.options[0].route == "compatible_tool"
    assert result.options[0].tool_id in {"suite", "voice"}
    assert "solo" not in [o.tool_id for o in result.options[:2]]


def test_unrelated_owned_tool_is_not_called_a_switch(catalog):
    routes = {o.tool_id: o.route for o in run(catalog, owned=["ledger"]).options}
    assert "switch" not in routes.values()


def test_overlapping_tool_is_a_switch(catalog):
    routes = {o.tool_id: o.route for o in run(catalog, owned=["suite"]).options}
    assert routes["suite"] == "native_add_on"
    catalog.tools = [t for t in catalog.tools if t.id in {"voice", "solo"}]
    routes = {o.tool_id: o.route for o in run(catalog, owned=["voice"]).options}
    assert routes["solo"] == "switch"


def test_add_on_cost_is_added_to_entry_price_for_new_buyers(catalog):
    costs = {o.tool_id: o.added_monthly_usd for o in run(catalog).options}
    assert costs["suite"] == 79


def test_unknown_price_never_outranks_known_price(catalog):
    assert run(catalog).options[0].added_monthly_usd is not None


def test_only_unknown_prices_give_no_winner(catalog):
    catalog.tools = [t for t in catalog.tools if t.id == "mystery"]
    result = run(catalog)
    assert result.outcome == "verify_with_vendor"
    assert result.winner_tool_id is None


def test_rejected_tools_are_excluded(catalog):
    catalog.tools = [t for t in catalog.tools if t.id == "banned"]
    assert run(catalog).outcome == "no_match"


def general_phone():
    return tool("anyphone", 20, [cap("phone")], trades=("all",), applicability="cross_industry")


def test_tool_made_for_another_business_is_set_aside(catalog):
    catalog.tools = [t for t in catalog.tools if t.id == "foreign"]
    result = run(catalog)
    assert result.options == [] and result.check_first == []
    assert result.outcome == "no_match"
    assert result.set_aside[0].reason == "Built for Restaurant, not HVAC"


def test_cheap_off_trade_tool_never_wins(catalog):
    result = run(catalog)
    assert "foreign" not in [o.tool_id for o in result.options]
    assert result.winner_tool_id != "foreign"
    assert result.tailored is True


def test_general_tool_stays_eligible_for_any_business(catalog):
    catalog.tools = [t for t in catalog.tools if t.id == "foreign"] + [general_phone()]
    for trade in ("hvac", "restaurant", "bakery", None):
        result = run(catalog, trade=trade)
        assert "anyphone" in [o.tool_id for o in result.options], trade


def test_tool_made_for_the_business_ranks_above_general_tool(catalog):
    catalog.tools = [t for t in catalog.tools if t.id == "voice"] + [general_phone()]
    result = run(catalog)
    assert [o.tool_id for o in result.options] == ["voice", "anyphone"]
    assert result.options[1].fit == "any_business"


def test_only_general_tools_says_so(catalog):
    catalog.tools = [general_phone()]
    result = run(catalog, trade="restaurant")
    assert result.winner_tool_id == "anyphone"
    assert result.tailored is False
    assert "built just for your kind of business" in result.tailoring_note


def test_unlisted_business_ranks_only_general_tools(catalog):
    result = run(catalog, trade="bakery")
    assert result.options == []
    assert result.check_first
    assert result.outcome == "verify_with_vendor"
    assert result.winner_tool_id is None
    assert '"bakery"' in result.tailoring_note


def test_unconfirmed_audience_is_never_the_winner(catalog):
    catalog.tools = [tool("vague", 5, [cap("phone")], applicability="unknown")]
    result = run(catalog)
    assert result.winner_tool_id is None
    assert [o.tool_id for o in result.check_first] == ["vague"]
    assert result.check_first[0].fit_note == "Not yet confirmed which kinds of business this suits"


def test_tool_you_already_use_counts_even_if_aimed_elsewhere(catalog):
    result = run(catalog, owned=["foreign"])
    assert result.outcome == "no_new_tool"
    assert result.options[0].fit == "you_use_it"


def test_no_catalog_match_is_said_plainly(catalog):
    result = run(catalog, problem="nothing")
    assert result.outcome == "no_match"
    assert result.options == []


def test_at_most_three_options(catalog):
    assert len(run(catalog).options) == 3


def test_stack_flags_duplicates(catalog):
    assert check_stack(catalog, ["voice", "solo"]).duplicates == ["Voice and Solo both cover phone"]


def test_add_on_does_not_count_as_a_duplicate(catalog):
    assert check_stack(catalog, ["suite", "voice"]).duplicates == []


def test_stack_total_is_unknown_when_a_price_is_unknown(catalog):
    result = check_stack(catalog, ["voice", "mystery"])
    assert result.total_monthly_usd is None
    assert result.known_monthly_usd == 100
    assert result.unknown_cost_tools == ["Mystery"]


def test_stack_total_when_all_prices_known(catalog):
    assert check_stack(catalog, ["voice", "ledger"]).total_monthly_usd == 130
