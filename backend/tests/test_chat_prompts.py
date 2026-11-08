import json
from pathlib import Path

import pytest

from app import db
from app.chat import ChatMemory, _prompt
from app.schemas import BusinessProfile


@pytest.mark.parametrize("plan", ["Core", "Legacy Gold 2019", None])
def test_live_prompt_preserves_exact_owned_plan_and_zero_added_budget(plan):
    catalog = db.load_catalog_file(Path(__file__).resolve().parent.parent / "data" / "catalog.json")
    profile = BusinessProfile(trade="hvac", owned=[{"tool_id": "jobber", "plan": plan}], budget_monthly_usd=0)
    prompt = _prompt(catalog, profile, ChatMemory())
    context = json.loads(prompt.split("What you remember in this session: ", 1)[1])
    assert context["owned"] == [{"tool_id": "jobber", "plan": plan}]
    assert context["budget_monthly_usd"] == 0
    assert context["trade"] == "hvac"
