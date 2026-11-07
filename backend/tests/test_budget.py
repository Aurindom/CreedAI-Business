from app.matching import recommend
from app.schemas import BusinessProfile
from conftest import cap, tool


def run(catalog, budget=None):
    return recommend(catalog, BusinessProfile(trade="hvac", budget_monthly_usd=budget), catalog.problem("calls"))


def every(result):
    return result.options + result.check_first


def test_no_budget_leaves_fit_unset(catalog):
    result = run(catalog)
    assert result.budget_note is None and all(o.within_budget is None for o in every(result))


def test_budget_compares_the_added_cost_only(catalog):
    result = run(catalog, 1000)
    assert "not your total bill" in result.budget_note
    for option in every(result):
        assert option.within_budget is (None if option.added_monthly_usd is None else True)


def test_unknown_cost_is_never_counted_as_fitting(catalog):
    catalog.tools = [tool("mystery", None, [cap("phone")])]
    (option,) = every(run(catalog, 0))
    assert option.added_monthly_usd is None and option.within_budget is None


def test_winner_over_budget_says_so(catalog):
    top = run(catalog).options[0]
    result = run(catalog, top.added_monthly_usd - 1)
    assert result.winner_tool_id == top.tool_id and result.options[0].within_budget is False
    assert f"more than your ${top.added_monthly_usd - 1:g}/mo budget" in result.message


def test_winner_within_budget_has_no_warning(catalog):
    top = run(catalog).options[0]
    result = run(catalog, top.added_monthly_usd)
    assert result.options[0].within_budget is True and "budget" not in result.message
