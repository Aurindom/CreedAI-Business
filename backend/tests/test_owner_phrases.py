import json
from pathlib import Path

import pytest

from app import db
from app.tasks import resolve_task

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
