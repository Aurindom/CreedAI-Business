import json
from pathlib import Path

import pytest

from app import db
from app.tasks import owner_excerpts, resolve_task

CASES = json.loads((Path(__file__).parent / "fixtures" / "owner_phrases.json").read_text(encoding="utf-8"))

@pytest.fixture(scope="module")
def real_catalog():
    return db.load_catalog_file(Path(__file__).parent.parent / "data" / "catalog.json")

@pytest.mark.parametrize("case", CASES, ids=[case["text"] for case in CASES])
def test_owner_phrase_regression(real_catalog, case):
    answer = resolve_task(real_catalog, case["text"])
    assert answer.status == case["status"]
    assert answer.problem_id == case["problem_id"]


def test_phrase_set_has_30_to_50_reviewable_examples():
    assert 30 <= len(CASES) <= 50
    assert len({case["text"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("text, card", [
    ("I never get around to replying to reviews", "review_replies"),
    ("I don't have time to answer reviews", "review_replies"),
    ("I can't keep up with review replies", "review_replies"),
])
def test_falling_behind_states_the_need(real_catalog, text, card):
    answer = resolve_task(real_catalog, text)
    assert (answer.status, answer.problem_id) == ("matched", card)
    assert owner_excerpts(text) == [text]


@pytest.mark.parametrize("text", [
    "I don't need help replying to reviews",
    "I don't want review replies",
    "I never reply to reviews",
])
def test_refusals_stay_negated(real_catalog, text):
    assert resolve_task(real_catalog, text).status == "ambiguous"
    assert owner_excerpts(text) == []
