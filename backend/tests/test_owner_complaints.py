"""Complaints worded with "never" or "can't" state a need; they are not the owner declining help.

Reported live on Hermes: "customers say they can never reach us" was mapped to missed calls, then refused as
"not affirmative" because of "never", and the owner saw "I could not validate that answer".
"""
import pytest

from app.tasks import affirmative_excerpt
from test_chat import calls, client, script, send  # noqa: F401  (client is a fixture)

COMPLAINTS = [
    'customers say they can never reach us',
    "customers can't reach us",
    'people cannot get through on the phone',
    "callers couldn't get hold of us",
    'we never answer the phone when we are busy',
    "we don't pick up during the lunch rush",
    "I can't call people back fast enough",
]
REFUSALS = [
    "I don't need help with calls",
    'I never reply to reviews',
    'we never want another phone tool',
    'no help with reviews please',
    "I don't need help with calls, customers can always reach us",
]


@pytest.mark.parametrize('text', COMPLAINTS)
def test_complaints_with_never_or_cant_are_affirmative(client, text):
    assert affirmative_excerpt(text, text, client.app.state.catalog)


@pytest.mark.parametrize('text', REFUSALS)
def test_real_refusals_stay_negated(client, text):
    assert not affirmative_excerpt(text, text, client.app.state.catalog)


def test_never_reach_us_gets_tools_instead_of_a_validation_failure(client, monkeypatch):
    message = 'customers say they can never reach us'
    script(monkeypatch, calls(('recommend_tools', {'problem_id': 'missed_calls', 'task_text': message})),
           calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message=message)
    assert any(e['type'] == 'recommendation' and e['problem_id'] == 'missed_calls' for e in events)
    assert not any(e['type'] == 'message_delta' and 'could not validate' in e['text'] for e in events)
