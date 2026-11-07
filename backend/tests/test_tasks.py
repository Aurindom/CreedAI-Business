import pytest

from app.tasks import resolve_task


@pytest.fixture
def phrased(catalog):
    words = {"calls": ["answer calls", "schedule"], "books": ["books", "bookkeeping", "schedule"], "nothing": []}
    for card in catalog.problem_cards:
        card.phrases = words[card.id]
    return catalog


@pytest.mark.parametrize("text, card", [
    ("Nobody ANSWERS my calls!", "calls"),
    ("my books are a mess", "books"),
    ("schedule answering the calls", "calls"),
])
def test_clear_text_matches_one_card(phrased, text, card):
    match = resolve_task(phrased, text)
    assert match.status == "matched" and match.problem_id == card and [c.id for c in match.choices] == [card]


def test_shared_word_asks_instead_of_guessing(phrased):
    match = resolve_task(phrased, "help me schedule")
    assert match.status == "ambiguous" and match.problem_id is None
    assert {c.id for c in match.choices} == {"calls", "books"}


@pytest.mark.parametrize("text", ["teleport my van", "", "!!!", "answer"])
def test_unknown_task_is_unsupported(phrased, text):
    match = resolve_task(phrased, text)
    assert match.status == "unsupported" and match.choices == [] and match.problem_id is None


def test_card_without_phrases_is_never_matched(phrased):
    assert all(resolve_task(phrased, t).problem_id != "nothing" for t in ["teleport", "nothing", "t w"])


def test_endpoint_returns_a_known_card_or_says_so(client):
    match = client.post("/api/tasks/resolve", json={"text": "I keep missing calls"}).json()
    assert match["status"] in ("matched", "ambiguous", "unsupported")
    known = {c["id"] for c in client.get("/api/problems").json()}
    assert {c["id"] for c in match["choices"]} <= known
    assert client.post("/api/tasks/resolve", json={"text": "zzqx"}).json()["status"] == "unsupported"


@pytest.mark.parametrize("text", ["", "   ", "x" * 301])
def test_endpoint_rejects_empty_or_long_text(client, text):
    assert client.post("/api/tasks/resolve", json={"text": text}).status_code == 422
