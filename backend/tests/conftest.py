import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import Capability, Catalog, Category, Fact, ProblemCard, Tool, Trade


def fact(value, source_type="vendor"):
    return Fact(status="present", value=value, source_url="https://example.com/p", source_type=source_type, checked="2026-11-06")


def cap(name, access="included", addon=None, plan=None, offer=None):
    extra = {"addon_monthly_usd": fact(addon)} if addon is not None else {}
    if offer is not None:
        extra["addon_offer"] = fact(offer)
    if plan is not None:
        extra["addon_from" if access == "add_on" else "included_from"] = fact(plan)
    access_fact = Fact(status="unknown") if access == "unknown" else fact(access)
    return Capability(capability=name, access=access_fact, **extra)


def tool(tool_id, price=None, caps=(), connects=None, trades=("hvac",), applicability="restricted", **extra):
    fields = {"status": "verified", **extra}
    fields["applicability"] = applicability
    if applicability != "unknown":
        fields["applicability_source"] = "https://example.com/who"
    if price is not None:
        fields["entry_monthly_usd"] = fact(price)
    if connects is not None:
        fields["connects_to"] = fact(connects)
    return Tool(id=tool_id, name=tool_id.title(), url="https://example.com", trades=list(trades), summary="x", capabilities=list(caps), **fields)


@pytest.fixture
def catalog():
    return Catalog(
        trades=[Trade(id="hvac", name="HVAC"), Trade(id="restaurant", name="Restaurant")],
        categories=[
            Category(id="talk", name="Calls", capabilities=["phone"]),
            Category(id="money", name="Money", capabilities=["bookkeeping", "jobs"]),
            Category(id="odd", name="Odd", capabilities=["teleport"]),
        ],
        problem_cards=[
            ProblemCard(id="calls", title="t", plain_words="w", capability="phone", trades=["hvac"]),
            ProblemCard(id="books", title="t", plain_words="w", capability="bookkeeping", trades=["hvac"]),
            ProblemCard(id="nothing", title="t", plain_words="w", capability="teleport", trades=["hvac"]),
        ],
        tools=[
            tool("suite", 50, [cap("phone", "add_on", 29, plan="Base"), cap("jobs", plan="Base")], connects=["ledger"], entry_plan=fact("Base")),
            tool("hidden", 80, [cap("phone", "add_on"), cap("jobs")]),
            tool("voice", 100, [cap("phone", plan="Core")], connects=["ledger"], entry_plan=fact("Core")),
            tool("solo", 60, [cap("phone", plan="Core")], entry_plan=fact("Core")),
            tool("mystery", None, [cap("phone")]),
            tool("ledger", 30, [cap("bookkeeping", plan="Core")], entry_plan=fact("Core")),
            tool("foreign", 10, [cap("phone", plan="Core")], trades=("restaurant",), entry_plan=fact("Core")),
            tool("banned", 1, [cap("phone")], status="rejected"),
        ],
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:
        yield test_client
