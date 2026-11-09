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
    known = {c["id"] for c in client.get("/api/problems").json()}
    for text in ("I keep missing calls", "my books are a mess"):
        match = client.post("/api/tasks/resolve", json={"text": text}).json()
        assert match["status"] == "matched" and match["problem_id"] in known
        assert [c["id"] for c in match["choices"]] == [match["problem_id"]]
    assert client.post("/api/tasks/resolve", json={"text": "zzqx"}).json()["status"] == "unsupported"


@pytest.mark.parametrize("text", ["", "   ", "x" * 301])
def test_endpoint_rejects_empty_or_long_text(client, text):
    assert client.post("/api/tasks/resolve", json={"text": text}).status_code == 422


@pytest.mark.parametrize("positive, negative", [
    ("I need help answering calls", "I don't need help answering calls"),
    ("I need help answering calls", "I do not want to answer calls myself"),
    ("my books are a mess", "my books are never a mess"),
])
def test_negation_never_gives_a_confident_match(phrased, positive, negative):
    assert resolve_task(phrased, positive).status == "matched"
    match = resolve_task(phrased, negative)
    assert match.status == "ambiguous" and match.problem_id is None and len(match.choices) == 1
    assert "confirm" in match.message


@pytest.mark.parametrize("text", [
    "I do not need help answering calls; I need bookkeeping",
    "I don't need help to answer calls. My books are a mess",
    "Not interested in answering calls, but my books are a mess",
])
def test_turning_one_task_down_matches_the_stated_one(phrased, text):
    match = resolve_task(phrased, text)
    assert match.status == "matched" and match.problem_id == "books" and [c.id for c in match.choices] == ["books"]


@pytest.mark.parametrize("text", [
    "I do not want to answer calls myself; I need bookkeeping",
    "Answer calls is not a worry for us; I need bookkeeping",
    "I don't need to answer calls; I need bookkeeping",
])
def test_negation_that_still_describes_a_problem_keeps_both(phrased, text):
    match = resolve_task(phrased, text)
    assert match.status == "ambiguous" and match.problem_id is None
    assert [c.id for c in match.choices] == ["books", "calls"]


def test_turning_down_a_task_with_two_stated_needs_still_asks(phrased):
    match = resolve_task(phrased, "I don't need help answering calls; help me schedule")
    assert match.status == "ambiguous" and match.problem_id is None


@pytest.mark.parametrize("text", [
    "I answer calls fine but my books are late",
    "Bookkeeping is done, however nobody can answer calls",
    "my books are a mess and nobody answers calls",
])
def test_two_needs_make_the_owner_choose(phrased, text):
    match = resolve_task(phrased, text)
    assert match.status == "ambiguous" and match.problem_id is None
    assert {c.id for c in match.choices} == {"calls", "books"}


def test_a_phrase_only_counts_inside_one_clause(phrased):
    assert resolve_task(phrased, "Please answer. Calls are fine.").status == "unsupported"


def test_a_shorter_phrase_inside_the_winning_one_is_not_a_second_need(phrased):
    phrased.problem("calls").phrases.append("schedule calls")
    match = resolve_task(phrased, "schedule calls")
    assert match.status == "matched" and match.problem_id == "calls"


def test_real_catalog_does_not_guess_on_mixed_sentences(client):
    match = client.post("/api/tasks/resolve", json={"text": "I answer calls fine but invoices are late"}).json()
    assert match["status"] == "ambiguous" and match["problem_id"] is None and len(match["choices"]) >= 2


def test_real_catalog_matches_a_need_next_to_a_turned_down_one(client):
    match = client.post("/api/tasks/resolve", json={"text": "I do not need help answering calls. I need help with bookkeeping."}).json()
    assert match["status"] == "matched" and match["problem_id"] == "bookkeeping"
