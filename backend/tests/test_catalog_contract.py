"""Release contracts for the real catalog, visible starters and Hermes route.

These exercise the application with real operation receipts and a fake model;
the separately metered live matrix checks the actual provider/Hermes boundary.
"""
from pathlib import Path
import json

import pytest

from app import chat, db
from app.penny_grounding import selected_task_ids
from app.tasks import affirmative_excerpt, owner_excerpts, resolve_task
from test_chat_hermes import FakeHermes, answer, frames, texts, hermes, rows

CATALOG = db.load_catalog_file(Path(__file__).parents[1] / 'data/catalog.json')
CARDS = CATALOG.problem_cards


def test_catalog_examples_are_unique_and_meaningful():
    examples = [card.plain_words.casefold().strip(' .!?') for card in CARDS]
    assert len(examples) == len(set(examples))
    assert all(len(example) >= 10 for example in examples)


@pytest.mark.parametrize('card', CARDS, ids=lambda card: card.id)
def test_every_catalog_example_has_its_own_bound_task(card):
    for text in (card.plain_words, card.plain_words.upper().strip(' .!?') + '!'):
        match = resolve_task(CATALOG, text)
        assert (match.status, match.problem_id) == ('matched', card.id)
        assert owner_excerpts(text, CATALOG)
        assert affirmative_excerpt(text, text.strip(' .!?'), CATALOG)
        body = chat.ChatRequest(conversation_id='example', message=text)
        assert selected_task_ids(CATALOG, body, {'problem_id': card.id, 'task_text': text}) == [card.id]


@pytest.mark.parametrize('card', CARDS, ids=lambda card: card.id)
def test_example_text_cannot_override_an_explicit_refusal(card):
    text = "I do not need help with this: " + card.plain_words
    assert resolve_task(CATALOG, text).status != 'matched'
    assert not affirmative_excerpt(text, card.plain_words.strip(' .!?'), CATALOG)
    body = chat.ChatRequest(conversation_id='refusal', message=text)
    with pytest.raises(ValueError):
        selected_task_ids(CATALOG, body, {'problem_id': card.id, 'task_text': card.plain_words})


@pytest.mark.parametrize('card', CARDS, ids=lambda card: card.id)
def test_every_catalog_example_through_chat_and_verified_operations(client, hermes, card):
    packages = []
    def script(package):
        packages.append(package)
        return answer(package, output=json.dumps({'claim_ids': [], 'followup_id': None}))
    fake = hermes(FakeHermes(script))
    events = frames(client.post('/api/chat', json={'conversation_id': 'catalog-' + card.id,
        'message': card.plain_words}))
    assert texts(events) and all(event['validation'] == 'validated' for event in texts(events))
    assert any(event['type'] == 'recommendation' and event['problem_id'] == card.id for event in events)
    assert card.id + ':decision' in packages[-1].required_claim_ids
    assert all(row[2] == 'succeeded' for row in rows())
    assert len([request for request in fake.requests if request[1] == '/v1/runs']) == 1


def test_exact_examples_still_preserve_multiple_needs_and_negation():
    first, second = CATALOG.problem('review_requests'), CATALOG.problem('appointment_booking')
    match = resolve_task(CATALOG, first.plain_words + ' ' + second.plain_words)
    assert match.status == 'ambiguous'
    assert {card.id for card in match.choices} == {first.id, second.id}
    assert resolve_task(CATALOG, 'I never get around to getting reviews').problem_id == 'review_requests'


@pytest.mark.parametrize('text,task', [
    ('Help customers book a time online', 'appointment_booking'),
    ('Please help me contact my customer list', 'email_marketing'),
    ('I need to get reviews from customers', 'review_requests'),
])
def test_related_owner_wording_does_not_fall_into_another_task(text, task):
    assert resolve_task(CATALOG, text).problem_id == task


def test_all_factual_ui_starters_have_a_known_task():
    source = (Path(__file__).parents[2] / 'frontend/src/chat/ChatPanel.jsx').read_text(encoding='utf-8')
    starters = source.split('const STARTERS = [', 1)[1].split(']', 1)[0]
    import re
    phrases = [text.replace("\\'", "'") for text in re.findall(r"'((?:\\.|[^'])*)'", starters)]
    assert len(phrases) >= 4
    for phrase in phrases:
        if phrase == 'Start with a few questions':
            continue
        assert resolve_task(CATALOG, phrase).status == 'matched', phrase
