from app.facts import NOT_CHECKED, tool_facts
from app.matching import recommend
from app.schemas import BusinessProfile, Fact
from conftest import cap, fact, tool


def by_label(t):
    return {f.label: f for f in tool_facts(t)}


def test_unknown_facts_stay_visible_as_unknown():
    facts = by_label(tool("t"))
    assert list(facts) == ["Entry price", "Setup", "Privacy", "Support"]
    assert all(not f.known and f.value == NOT_CHECKED and f.state == "not_checked" for f in facts.values())


def test_researched_unknown_says_why():
    hidden = Fact(status="unknown", note="Sales contact only.")
    price = by_label(tool("t", entry_monthly_usd=hidden))["Entry price"]
    assert price.value == "Confirm with the service" and price.note == "Sales contact only."
    assert price.state == "unresolved"


def test_unresolved_fact_keeps_where_we_looked():
    looked = Fact(status="unknown", note="Pricing page needs a sales call.", source_url="https://example.com/pricing", checked="2026-11-07")
    price = by_label(tool("t", entry_monthly_usd=looked))["Entry price"]
    assert price.state == "unresolved" and str(price.source_url) == "https://example.com/pricing"
    assert str(price.checked) == "2026-11-07"


def test_known_price_shows_plan_and_source():
    price = by_label(tool("t", 49, entry_plan=fact("Core")))["Entry price"]
    assert price.known and price.state == "known" and price.value == "$49/mo, Core plan"
    assert str(price.source_url) == "https://example.com/p"
    assert str(price.checked) == "2026-11-06"


def test_free_plan_reads_as_free():
    assert by_label(tool("t", 0))["Entry price"].value == "Free"


def test_vendor_claim_keeps_its_source_type():
    setup = by_label(tool("t", setup_effort=fact("low")))["Setup"]
    assert setup.value == "Low effort" and setup.source_type == "vendor"


def ranked(catalog, tools):
    catalog.tools = tools
    result = recommend(catalog, BusinessProfile(trade="hvac"), catalog.problem("calls"))
    return [o.tool_id for o in result.options]


def test_cheaper_known_price_ranks_first_on_same_route(catalog):
    assert ranked(catalog, [tool("dear", 90, [cap("phone")]), tool("cheap", 20, [cap("phone")])]) == ["cheap", "dear"]


def test_same_price_falls_back_to_name(catalog):
    assert ranked(catalog, [tool("zeta", 20, [cap("phone")]), tool("alpha", 20, [cap("phone")])]) == ["alpha", "zeta"]


def test_unknown_price_ranks_after_known_price(catalog):
    assert ranked(catalog, [tool("hidden", None, [cap("phone")]), tool("pricey", 500, [cap("phone", plan="Core")], entry_plan=fact("Core"))]) == ["pricey", "hidden"]
