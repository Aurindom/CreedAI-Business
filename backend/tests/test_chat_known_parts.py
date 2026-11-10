"""Memory and favourites questions are answered by the app, and survive a model outage.

The wording lists are deliberately wider than the reported phrases: recognition is
by shape, so unseen paraphrases, punctuation and filler words have to behave the same.
"""
import logging
import sqlite3

import pytest

from app import chat, conversation_plan as planner
from app.agent import readiness
from conftest import account_header
from test_chat_hermes import FakeHermes, answer, frames, hermes  # noqa: F401
from test_chat_spend_meter import RESERVE, gateway, spent  # noqa: F401
from test_conversation_journeys import public_reads  # noqa: F401

MEMORY = {'business_description': 'kite repair studio'}
BUSINESS = [
    'what business do I have?',
    'What business do I have',
    'WHAT IS MY BUSINESS???',
    'So, what’s my business type again?',
    'do you know what kind of business I run?',
    'Can you tell me what my business is?',
    'which business do I own',
    'Arkadio, remind me what my business is please',
    'what did I tell you about my business?',
    "don't you remember my business?",
    'what do you know about my business',
    'What type of business am I running?',
]
FAVOURITES = [
    'Do I have any favourite tools yet?',
    'do i have any favorites',
    'Have I saved any tools so far?',
    'any favourites?',
    "What's in my favourites right now?",
    'how many favourites do I have?',
    'show me my bookmarks',
    'Could you list my saved tools please',
    'which tools are in my favourites',
    'Is there anything in my favourites yet?',
]
NOT_OWN_FACTS = [
    'how do I attract customers',
    'what is my business missing',
    'tell me about my business plan',
    'what business should I start',
    'If I ran a bakery, what business do I have?',
    'do I have any tools for invoicing',
    'should I have any favourite tools',
    'what do customers think of my business',
    'Remember to send invoices on Friday',
]


def kinds(client, message, memory=MEMORY):
    plan = planner.local_plan(message, chat.ChatMemory(**memory), client.app.state.catalog)
    return [step.kind for step in plan.steps] if plan else None


def ask(client, message, memory=MEMORY, user=None, conversation='known-parts'):
    response = client.post('/api/chat', headers=account_header(user) if user else {}, json={
        'conversation_id': conversation, 'message': message, 'memory': memory, 'history': [], 'ui_version': 3})
    assert response.status_code == 200
    events = frames(response)
    assert events[-1] == {'type': 'done'}
    text = '\n'.join(event.get('text', '') for event in events if event['type'] == 'message_delta')
    return events, text, [event.get('code') for event in events if event['type'] == 'error']


@pytest.fixture
def no_budget(monkeypatch, hermes, gateway):
    """The model path is healthy but the spend cap is used up. Any model call fails the test."""
    fake = hermes(FakeHermes(answer))
    monkeypatch.setattr(chat, 'chat_available', lambda: True)
    monkeypatch.setenv('CHAT_SPEND_CAP_USD', str(spent() + RESERVE / 2))
    return fake


@pytest.mark.parametrize('message', BUSINESS)
def test_business_questions_are_recognised_by_shape(client, message):
    assert kinds(client, message) == ['recall']


@pytest.mark.parametrize('message', FAVOURITES)
def test_favourites_questions_are_recognised_by_shape(client, message):
    assert kinds(client, message) == ['favourites_list']


@pytest.mark.parametrize('message', NOT_OWN_FACTS)
def test_other_questions_are_not_mistaken_for_memory(client, message):
    found = kinds(client, message) or []
    assert 'recall' not in found and 'favourites_list' not in found


def test_restating_the_known_business_is_a_recall_not_a_new_task(client):
    assert kinds(client, 'Remember I have a coffee shop?', {'business_description': 'coffee shop'}) == ['recall']
    assert kinds(client, 'Remember I have a coffee shop?', MEMORY) != ['recall']


def test_how_to_and_writes_keep_their_meaning(client):
    assert kinds(client, 'How do I see my favourites?') == ['help']
    assert kinds(client, 'Save Jobber to favourites') == ['favourites_save']
    assert kinds(client, 'Remove Jobber from favourites') == ['favourites_remove']


@pytest.mark.parametrize('message', BUSINESS)
def test_business_answer_needs_no_model_and_no_budget(client, public_reads, no_budget, message):
    before = spent()
    _, text, errors = ask(client, message)
    assert 'kite repair studio' in text and not errors
    assert not no_budget.requests and not public_reads and spent() == pytest.approx(before)


@pytest.mark.parametrize('memory', [{}, {'business_forgotten': True}])
def test_unknown_business_is_not_invented(client, public_reads, no_budget, memory):
    _, text, errors = ask(client, 'what business do I have?', memory)
    assert text and not errors and 'kite' not in text
    assert not no_budget.requests


@pytest.mark.parametrize('message', FAVOURITES)
def test_guest_is_told_to_sign_in_not_that_the_list_is_empty(client, public_reads, no_budget, message):
    _, text, errors = ask(client, message)
    assert 'Sign in' in text and 'no saved favourite' not in text and not errors
    assert not no_budget.requests


@pytest.mark.parametrize('message', FAVOURITES)
def test_account_list_is_read_from_the_account(client, public_reads, no_budget, message):
    _, text, _ = ask(client, message, user=1)
    assert 'no saved favourite' in text
    assert client.put('/api/favourites/jobber', headers=account_header(1)).status_code < 300
    _, text, errors = ask(client, message, user=1)
    assert 'Jobber' in text and 'no saved favourite' not in text and not errors
    _, text, _ = ask(client, message, user=2)
    assert 'Jobber' not in text
    assert not no_budget.requests


@pytest.mark.parametrize('message', FAVOURITES)
def test_failed_read_never_claims_an_empty_list(client, public_reads, no_budget, monkeypatch, message):
    from app import favourites

    def failed(*args, **kwargs):
        raise sqlite3.OperationalError('synthetic failure')
    monkeypatch.setattr(favourites, 'account_tools', failed)
    _, text, _ = ask(client, message, user=1)
    assert 'could not confirm' in text and 'no saved favourite' not in text


COMPOUND = 'What business do I have? How do I attract customers?'


def test_budget_refusal_still_answers_the_known_part(client, public_reads, no_budget, caplog):
    before = spent()
    with caplog.at_level(logging.WARNING, logger=chat.logger.name):
        events, text, errors = ask(client, COMPOUND)
    assert 'kite repair studio' in text and 'How do I attract customers' in text and 'budget' in text
    assert not errors and 'Try again' not in text
    assert not no_budget.requests and not public_reads and spent() == pytest.approx(before)
    assert 'hermes_bail spend_reserve_refused' in caplog.text and 'hermes_degraded ai_budget_reached' in caplog.text
    assert [event['validation'] for event in events if event['type'] == 'message_delta'][-1] == 'fallback'


@pytest.mark.parametrize('fast_path', ['true', 'false'])
@pytest.mark.parametrize('code', ['mcp_unreachable', 'hermes_unreachable', 'gateway_unreachable', 'gateway_exhausted'])
def test_outage_does_not_turn_a_memory_question_into_intake(client, public_reads, hermes, monkeypatch, code, fast_path):
    fake = hermes(FakeHermes(answer))
    monkeypatch.setenv('CHAT_CATALOG_FAST_PATH', fast_path)

    async def down():
        return readiness.Readiness(False, code)
    monkeypatch.setattr(readiness, 'check', down)
    before = spent()
    _, text, errors = ask(client, COMPOUND)
    assert 'kite repair studio' in text and 'How do I attract customers' in text and not errors
    assert ('budget' if code == 'gateway_exhausted' else 'unavailable') in text
    assert not fake.requests and spent() == pytest.approx(before)


def test_daily_limit_still_answers_the_known_part(client, public_reads, hermes, gateway, monkeypatch):
    fake = hermes(FakeHermes(answer))
    monkeypatch.setenv('CHAT_DAILY_MESSAGES', '0')
    before = spent()
    _, text, errors = ask(client, COMPOUND)
    assert 'kite repair studio' in text and 'request limit' in text and not errors
    assert not fake.requests and spent() == pytest.approx(before)


def test_a_failed_run_still_answers_the_known_part(client, public_reads, hermes, gateway):
    fake = hermes(FakeHermes(answer, start_status=503))
    _, text, errors = ask(client, COMPOUND)
    assert 'kite repair studio' in text and 'How do I attract customers' in text and not errors
    assert fake.requests


def test_degraded_turn_reads_but_never_writes(client, public_reads, no_budget):
    assert client.put('/api/favourites/mailchimp', headers=account_header(1)).status_code < 300
    message = 'What are my favourite tools? Save Jobber to favourites. How do I attract customers?'
    events, text, errors = ask(client, message, user=1)
    assert 'Mailchimp' in text and 'Saved Jobber' not in text and not errors
    assert 'Save Jobber to favourites' in text and 'How do I attract customers' in text
    assert not [event for event in events if event['type'] == 'favourites_changed']
    assert [row['tool_id'] for row in client.get('/api/favourites', headers=account_header(1)).json()] == ['mailchimp']
    assert not no_budget.requests


def test_degraded_guest_is_not_told_the_list_is_empty(client, public_reads, no_budget):
    _, text, errors = ask(client, 'Do I have any favourite tools yet? How do I attract customers?')
    assert 'Sign in' in text and 'no saved favourite' not in text and not errors


def test_a_write_alone_is_not_run_when_the_model_refuses(client, public_reads, no_budget):
    events, text, errors = ask(client, 'Save Jobber to favourites and tell me how to attract customers', user=1)
    assert 'Saved Jobber' not in text
    assert client.get('/api/favourites', headers=account_header(1)).json() == []


def test_a_model_only_question_gets_the_honest_refusal(client, public_reads, no_budget):
    _, text, errors = ask(client, 'How do I attract customers?')
    assert errors == ['ai_budget_reached'] and 'kite' not in text
    assert not no_budget.requests


def test_a_healthy_model_still_gets_the_whole_compound_request(client, public_reads, hermes, gateway):
    fake = hermes(FakeHermes(answer))
    _, _, errors = ask(client, COMPOUND)
    assert fake.requests and 'ai_budget_reached' not in errors


def test_known_parts_are_only_read_only(client):
    memory, catalog = chat.ChatMemory(**MEMORY), client.app.state.catalog
    known, rest = planner.known_parts('Forget my business. What are my favourites? Why is the sky blue?', memory, catalog)
    assert [step.kind for step in known.steps] == ['favourites_list'] and len(rest) == 2
    assert planner.known_parts('what business do I have?', memory, catalog)[0] is None
    assert planner.known_parts('Why is the sky blue?', memory, catalog)[0] is None


@pytest.mark.parametrize('message', [
    'Arkadio, remind me what my business is please',
    'what do you think my business is missing',
    'do you know what my business is called',
    'tell me whether my business is ready for AI',
])
def test_a_question_about_the_business_never_overwrites_it(client, public_reads, no_budget, message):
    events, _, _ = ask(client, message)
    stored = [event['memory']['business_description'] for event in events if event['type'] == 'memory']
    assert all(value == 'kite repair studio' for value in stored)


@pytest.mark.parametrize('message,expected', [
    ('My business is a dog grooming salon', 'a dog grooming salon'),
    ('Hi, my business is plumbing', 'plumbing'),
    ('Actually my business is a bakery now', 'a bakery now'),
])
def test_a_statement_still_declares_the_business(message, expected):
    from app.conversation_state import business_description
    assert (business_description(message) or '').startswith(expected.split(' now')[0])


def test_heart_and_chat_share_one_list_per_account(client, public_reads, no_budget):
    """The heart button (REST) and the chat write to the same account list, in both directions."""
    saved = lambda user: sorted(row['tool_id'] for row in client.get('/api/favourites', headers=account_header(user)).json())
    assert client.put('/api/favourites/jobber', headers=account_header(1)).status_code < 300
    _, text, errors = ask(client, 'What are my favourite tools?', user=1)
    assert 'Jobber' in text and not errors
    events, text, errors = ask(client, 'Save Mailchimp to favourites', user=1)
    assert not errors and [event for event in events if event['type'] == 'favourites_changed']
    assert saved(1) == ['jobber', 'mailchimp']
    events, _, errors = ask(client, 'Remove Jobber from favourites', user=1)
    assert not errors and saved(1) == ['mailchimp']
    assert client.delete('/api/favourites/mailchimp', headers=account_header(1)).status_code < 300
    _, text, _ = ask(client, 'Do I have any favourite tools yet?', user=1)
    assert 'no saved favourite' in text and 'Mailchimp' not in text
    assert saved(2) == []
    assert not no_budget.requests


def test_a_guest_chat_save_changes_no_account(client, public_reads, no_budget):
    _, text, _ = ask(client, 'Save Jobber to favourites')
    assert 'Saved Jobber' not in text
    assert client.get('/api/favourites', headers=account_header(1)).json() == []
