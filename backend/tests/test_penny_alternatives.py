import pytest

from app import chat
from app.agent.evidence import build_evidence
from app.agent.grounding import FALLBACK
from app.penny_grounding import ActionContextError, recommendation_catalog, recommendation_package, selected_task_ids
from app.schemas import BusinessProfile
from test_chat import client, calls, reply, script, send


@pytest.mark.parametrize('task,excluded', [
    ('review_replies', 'google_business_profile'),
    ('bookkeeping', 'quickbooks_online'),
    ('missed_calls', 'jobber'),
])
def test_alternatives_reuse_active_task_without_permanent_rejection(client, monkeypatch, task, excluded):
    message = 'Is there any alternate for this tool?'
    script(monkeypatch,
           calls(('recommend_tools', {'problem_id': task, 'task_text': message,
                                     'use_active_task': True, 'exclude_tool_ids': [excluded]})),
           calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message, profile={'trade': 'hvac'}, memory={'active_task_ids': [task]},
                  history=[{'role': 'assistant', 'text': f'I showed a tool for {task}.'}])
    assert any(event.get('surface') == 'recommendation' for event in events), events
    card = next(event for event in events if event.get('surface') == 'recommendation')
    rec = card['messages'][1]['updateComponents']['components'][0]['recommendation']
    assert excluded not in [option['tool_id'] for option in rec['options'] + rec['check_first']]
    assert 'Looking for alternatives to' in rec['message']
    assert 'https://' in rec['message']
    assert not any(event.get('validation') == 'fallback' for event in events)
    assert FALLBACK not in str(events)
    memory = [event['memory'] for event in events if event['type'] == 'memory'][-1]
    assert memory['active_task_ids'] == [task]
    assert memory['ruled_out'] == []
    assert excluded not in memory['owned']
    if task == 'review_replies':
        assert not rec['options'] and not rec['check_first']
        assert 'No other tool in our catalog is confirmed' in rec['message']
    if task == 'missed_calls':
        assert rec['options'] or rec['check_first']


def test_excluding_owned_tool_preserves_other_subscription_context(client):
    catalog = client.app.state.catalog
    profile = BusinessProfile(trade='hvac', owned=[{'tool_id': 'quickbooks_online', 'plan': 'Plus'}], budget_monthly_usd=50)
    package = recommendation_package(catalog, profile, ['bookkeeping'], {'exclude_tool_ids': ['quickbooks_online']})
    assert 'quickbooks_online' not in package.winner_tool_ids
    assert not any(claim.tool_id == 'quickbooks_online' for claim in package.claims)
    # The original profile and catalog still include the subscription after the lookup.
    assert profile.owned[0].tool_id == 'quickbooks_online'
    assert catalog.tool('quickbooks_online')
    assert 'quickbooks_online' in build_evidence(catalog, profile, ['bookkeeping']).winner_tool_ids


@pytest.mark.parametrize('terminal', [
    calls(('submit_answer', {'claim_ids': ['fabricated_price']})),
    reply('ImaginaryService costs $999 and is the perfect replacement.'),
])
def test_invalid_model_answer_after_alternatives_lookup_uses_only_checked_records(client, monkeypatch, terminal):
    message = 'Are there alternatives to that tool?'
    script(monkeypatch,
           calls(('recommend_tools', {'problem_id': 'review_replies', 'task_text': message,
                                     'use_active_task': True, 'exclude_tool_ids': ['google_business_profile']})),
           terminal)
    events = send(client, message, memory={'active_task_ids': ['review_replies']})
    rendered = ''.join(event.get('text', '') for event in events if event['type'] == 'message_delta')
    assert 'No other tool in our catalog is confirmed' in rendered
    assert FALLBACK not in rendered
    assert 'ImaginaryService' not in rendered and '$999' not in rendered
    assert any(event.get('validation') == 'validated' for event in events)


@pytest.mark.parametrize('excluded', [['not-a-catalog-tool'], ['jobber', 'jobber'], 'jobber', [None], ['jobber'] * 4])
def test_invalid_alternative_exclusions_are_rejected(client, excluded):
    with pytest.raises((KeyError, ValueError)):
        recommendation_catalog(client.app.state.catalog, {'exclude_tool_ids': excluded})


@pytest.mark.parametrize('message,active,selected,excerpt', [
    ('Help with my books', ['review_replies'], 'review_replies', 'Help with my books'),
    ('I do not want help with that', ['review_replies'], 'review_replies', 'want help with that'),
    ('Any alternatives?', [], 'review_replies', 'Any alternatives'),
    ('Any alternatives?', ['review_replies', 'bookkeeping'], 'review_replies', 'Any alternatives'),
    ('Any alternatives?', ['review_replies'], 'bookkeeping', 'Any alternatives'),
    ('Any alternatives?', ['review_replies'], 'review_replies', 'Invented owner request'),
])
def test_context_reference_cannot_override_task_negation_or_ambiguity(client, message, active, selected, excerpt):
    body = chat.ChatRequest(conversation_id='context-test', message=message, memory={'active_task_ids': active})
    with pytest.raises(ActionContextError):
        selected_task_ids(client.app.state.catalog, body, {'problem_id': selected, 'task_text': excerpt, 'use_active_task': True})
