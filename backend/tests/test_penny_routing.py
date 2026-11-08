"""Conversation-level intent routing without phrase-specific production rules."""
import pytest

from app import chat
from app.penny_grounding import ActionContextError, selected_task_ids
from app.tasks import resolve_task
from test_chat import client, calls, script, send
from test_penny_grounding import text, package_from


@pytest.mark.parametrize('owner_text,task', [
    ('Taking calls for reservation', 'appointment_booking'),
    ('People hang up before we can speak', 'missed_calls'),
    ('Organising who covers each evening', 'staff_scheduling'),
    ('Keeping track of money coming in and going out', 'bookkeeping'),
])
def test_semantic_owner_request_reaches_catalog_answer(client, monkeypatch, owner_text, task):
    assert resolve_task(client.app.state.catalog, owner_text).status == 'unsupported'
    script(monkeypatch,
           calls(('recommend_tools', {'problem_id': task, 'task_text': owner_text})),
           calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message=owner_text)
    assert any(event.get('surface') == 'recommendation' for event in events)
    assert not any(event['type'] == 'clarify' for event in events)
    assert any(event.get('validation') == 'validated' for event in events)
    memory = [event['memory'] for event in events if event['type'] == 'memory'][-1]
    assert memory['active_task_ids'] == [task]
    assert memory['pending_question'] is None


@pytest.mark.parametrize('meta', [False, True])
def test_answer_to_task_question_advances_instead_of_repeating(client, monkeypatch, meta):
    request = 'Taking calls for reservation'
    history = [{'role': 'assistant', 'text': 'What would you like help with?'}]
    if meta:
        history += [{'role': 'user', 'text': request},
                    {'role': 'assistant', 'text': 'What would you like help with?'}]
    seen = script(monkeypatch,
                  calls(('ask_owner', {'question_id': 'task'})),
                  calls(('recommend_tools', {'problem_id': 'appointment_booking', 'task_text': request})),
                  calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message='why am i getting the same reply' if meta else request,
                  profile={'trade': 'coffee_shop'}, history=history,
                  memory={'budget_monthly_usd': 1000, 'background_done': True, 'pending_question': 'task'})
    assert len(seen) == 3
    assert not any(event['type'] == 'clarify' for event in events)
    assert any(event.get('surface') == 'recommendation' for event in events)
    assert 'What would you like help with?' not in text(events)
    assert any(event.get('validation') == 'validated' for event in events)
    memory = [event['memory'] for event in events if event['type'] == 'memory'][-1]
    assert memory['budget_monthly_usd'] == 1000


def test_known_task_does_not_restart_intake(client, monkeypatch):
    seen = script(monkeypatch, calls(('ask_owner', {'question_id': 'task'})))
    events = send(client, message='My books are behind')
    assert len(seen) == 1
    assert not any(event['type'] == 'clarify' for event in events)
    assert any(event.get('validation') == 'validated' for event in events)


@pytest.mark.parametrize('message,task,excerpt', [
    ('I need bookkeeping help', 'missed_calls', 'I need bookkeeping help'),
    ('schedule', 'staff_scheduling', 'schedule'),
    ('I do not need telephone assistance', 'missed_calls', 'telephone assistance'),
    ('Help with incoming conversations', 'missed_calls', 'a fabricated request'),
])
def test_semantic_selection_cannot_override_clear_ambiguous_or_negated_request(client, message, task, excerpt):
    body = chat.ChatRequest(conversation_id='test', message=message)
    with pytest.raises(ActionContextError):
        selected_task_ids(client.app.state.catalog, body, {'problem_id': task, 'task_text': excerpt})


def test_assistant_text_cannot_be_used_as_owner_task_evidence(client):
    body = chat.ChatRequest(conversation_id='test', message='Can you help me?',
                            history=[{'role': 'assistant', 'text': 'Handle incoming telephone enquiries'}])
    with pytest.raises(ActionContextError):
        selected_task_ids(client.app.state.catalog, body, {
            'problem_id': 'missed_calls', 'task_text': 'Handle incoming telephone enquiries'})


def test_task_clarification_choices_use_selected_catalog_categories(client, monkeypatch):
    ids = ['missed_calls', 'appointment_booking']
    script(monkeypatch, calls(('ask_owner', {'question_id': 'task', 'problem_ids': ids})))
    events = send(client, message='Help me decide')
    prompt = next(event for event in events if event['type'] == 'clarify')
    assert prompt['choices'][:-1] == [client.app.state.catalog.problem(pid).title for pid in ids]
    memory = next(event['memory'] for event in events if event['type'] == 'memory')
    assert memory['pending_question'] == 'task'


def test_task_question_without_relevant_categories_never_shows_default_options(client, monkeypatch):
    ids = ['missed_calls', 'appointment_booking']
    script(monkeypatch,
           calls(('ask_owner', {'question_id': 'task'})),
           calls(('ask_owner', {'question_id': 'task', 'problem_ids': ids})))
    events = send(client, message='Help me decide')
    prompts = [event for event in events if event['type'] == 'clarify']
    assert len(prompts) == 1
    assert prompts[0]['choices'][:-1] == [client.app.state.catalog.problem(pid).title for pid in ids]


def test_context_update_after_semantic_routing_keeps_the_selected_task(client, monkeypatch):
    request = 'Taking calls for reservation'
    seen = script(monkeypatch,
                  calls(('recommend_tools', {'problem_id': 'appointment_booking', 'task_text': request})),
                  calls(('update_memory', {'budget_monthly_usd': 1000})),
                  calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message=request)
    assert any(claim.id == 'appointment_booking:decision' for claim in package_from(seen[-1]).claims)
    assert any(event.get('validation') == 'validated' for event in events)


def test_pending_budget_answer_keeps_active_task(client, monkeypatch):
    script(monkeypatch, calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message='$1000', memory={
        'active_task_ids': ['appointment_booking'], 'pending_question': 'budget',
        'budget_monthly_usd': 1000})
    assert any(event.get('validation') == 'validated' for event in events)
    assert 'What would you like help with?' not in text(events)


def test_multiple_semantic_needs_keep_both_categories(client, monkeypatch):
    owner_text = 'Handling incoming telephone enquiries and organising reservations'
    seen = script(monkeypatch,
                  calls(('recommend_tools', {'problem_id': 'missed_calls', 'task_text': 'Handling incoming telephone enquiries'}),
                        ('recommend_tools', {'problem_id': 'appointment_booking', 'task_text': 'organising reservations'})),
                  calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message=owner_text)
    package = package_from(seen[-1])
    assert {'missed_calls:decision', 'appointment_booking:decision'} <= {claim.id for claim in package.claims}
    memory = [event['memory'] for event in events if event['type'] == 'memory'][-1]
    assert memory['active_task_ids'] == ['missed_calls', 'appointment_booking']
    assert any(event.get('validation') == 'validated' for event in events)
