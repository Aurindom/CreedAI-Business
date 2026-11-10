"""An owner who says they already use a tool is never treated as a new buyer of it."""
import pytest

from app.matching import recommend
from app.ownership import stated_ownership
from app.schemas import BusinessProfile
from test_chat import calls, client, script, send  # noqa: F401  (client is a fixture)

REPORTED = 'we already use QuickBooks Simple Start, my books are behind'


@pytest.mark.parametrize('owner_text,expected', [
    (REPORTED, [('quickbooks_online', 'Simple Start')]),
    ('We use QuickBooks', [('quickbooks_online', None)]),
    ('QuickBooks is what we use', [('quickbooks_online', None)]),
    ("I'm on Jobber Grow and pay for Mailchimp", [('jobber', 'Grow'), ('mailchimp', None)]),
    ("we don't use QuickBooks", []),
    ('should I buy QuickBooks?', []),
    ('thinking about Square for Restaurants', []),
    ('our books are behind', []),
    ('We use QuickBooks Platinum', [('quickbooks_online', None)]),
    ('Can I use Jobber?', []),
    ('Should we use Jobber?', []),
    ('I might use Jobber', []),
    ('I want to use Jobber', []),
    ('I have a question about Jobber', []),
    ('We currently use Jobber', [('jobber', None)]),
    ('Our team has Jobber', [('jobber', None)]),
])
def test_stated_ownership(client, owner_text, expected):
    assert sorted(stated_ownership(client.app.state.catalog, owner_text)) == sorted(expected)


def test_reported_message_is_no_new_tool_even_if_the_model_skips_memory(client, monkeypatch):
    seen = script(monkeypatch,
                  calls(('recommend_tools', {'problem_id': 'bookkeeping', 'task_text': 'my books are behind'})),
                  calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message=REPORTED)
    memory = [event['memory'] for event in events if event['type'] == 'memory']
    assert memory and 'quickbooks_online' in memory[0]['owned']
    assert memory[0]['plans'] == {'quickbooks_online': 'Simple Start'}
    assert 'Simple Start' in seen[0][0]['content']
    profile = BusinessProfile(owned=[{'tool_id': 'quickbooks_online', 'plan': 'Simple Start'}])
    expected = recommend(client.app.state.catalog, profile, client.app.state.catalog.problem('bookkeeping'))
    assert expected.outcome == 'no_new_tool'
    cards = [event for event in events if event.get('surface') == 'recommendation']
    assert cards, 'a recommendation card is shown'
    card = cards[-1]['messages'][1]['updateComponents']['components'][0]['recommendation']
    assert card['outcome'] == 'no_new_tool'


def test_plan_survives_into_the_next_turn(client, monkeypatch):
    script(monkeypatch,
           calls(('recommend_tools', {'problem_id': 'bookkeeping', 'task_text': 'my books are behind'})),
           calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message='my books are behind',
                  memory={'owned': ['quickbooks_online'], 'plans': {'quickbooks_online': 'Simple Start'}, 'background_done': True})
    card = [event for event in events if event.get('surface') == 'recommendation'][-1]
    assert card['messages'][1]['updateComponents']['components'][0]['recommendation']['outcome'] == 'no_new_tool'


def test_unknown_tools_and_long_plans_are_dropped(client, monkeypatch):
    script(monkeypatch, calls(('ask_owner', {'question_id': 'task'})))
    events = send(client, message='hello', memory={'owned': ['made_up'], 'plans': {'made_up': 'x', 'quickbooks_online': ' ' * 3}})
    memory = [event['memory'] for event in events if event['type'] == 'memory']
    assert all('made_up' not in m['owned'] and m['plans'] == {} for m in memory)
