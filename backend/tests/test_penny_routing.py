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
    ('I do not need help because answering phone calls is easy', 'missed_calls', 'answering phone calls'),
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


@pytest.mark.parametrize('recommend_first', [False, True])
def test_resource_shortage_routes_to_tools_for_latest_business_type(client, monkeypatch, recommend_first):
    owner_text = 'i am running a local hvac business, as it is a small business i dont have enough manpower to attent the cutomer calls, so i missing out of lot of cutomers.'
    actions = [('update_memory', {'trade': 'hvac'}),
               ('recommend_tools', {'problem_id': 'missed_calls', 'task_text': 'i missing out of lot of cutomers'})]
    script(monkeypatch,
           calls(*(list(reversed(actions)) if recommend_first else actions)),
           calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message=owner_text, memory={'trade': 'bakery'})
    assert not any(event['type'] == 'clarify' for event in events)
    surface = next(event for event in events if event.get('surface') == 'recommendation')
    component = surface['messages'][1]['updateComponents']['components'][0]
    rec = component['recommendation']
    assert rec['problem_id'] == 'missed_calls'
    assert rec['options'] or rec['check_first']
    assert all(row['tool_id'] not in ('slang_ai', 'square_restaurants') for row in rec['options'] + rec['check_first'])
    assert component['taskPurpose'] == 'answering phone calls'
    assert [event['memory'] for event in events if event['type'] == 'memory'][-1]['trade'] == 'hvac'
    assert next(event for event in events if event['type'] == 'recommendation')['profile']['trade'] == 'hvac'


@pytest.mark.parametrize('confirmation', ['yes', 'ok', 'please proceed'])
def test_confirmed_task_produces_tool_list(client, monkeypatch, confirmation):
    script(monkeypatch,
           calls(('recommend_tools', {'problem_id': 'missed_calls', 'task_text': confirmation})),
           calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message=confirmation, profile={'trade': 'hvac'}, memory={
        'pending_question': 'task', 'pending_task_ids': ['missed_calls']})
    assert any(event.get('surface') == 'recommendation' for event in events)
    assert any(event.get('validation') == 'validated' for event in events)
    assert not any(event['type'] == 'clarify' for event in events)


def test_legacy_task_followup_confirmation_recovers_catalog_choice(client, monkeypatch):
    script(monkeypatch,
           calls(('recommend_tools', {'problem_id': 'missed_calls', 'task_text': 'yes'})),
           calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message='yes', profile={'trade': 'hvac'}, history=[
        {'role': 'user', 'text': 'I am losing customers when I cannot take calls'},
        {'role': 'assistant', 'text': "Let's narrow that down. Explore: Calls go unanswered"}])
    assert any(event.get('surface') == 'recommendation' for event in events)
    assert any(event.get('validation') == 'validated' for event in events)


def test_declining_or_ambiguous_confirmation_cannot_select_pending_tool_list(client):
    for answer, ids in [('no', ['missed_calls']), ('yes', ['missed_calls', 'appointment_booking'])]:
        body = chat.ChatRequest(conversation_id='test', message=answer, memory={
            'pending_question': 'task', 'pending_task_ids': ids})
        with pytest.raises(ActionContextError):
            selected_task_ids(client.app.state.catalog, body, {'problem_id': 'missed_calls', 'task_text': answer})


def test_unresolved_request_cannot_finish_with_generic_clarification_tool(client):
    from app.penny_grounding import request_package
    from app.schemas import BusinessProfile
    body = chat.ChatRequest(conversation_id='test', message='Help me decide what to use')
    package = request_package(client.app.state.catalog, BusinessProfile(), body)
    payload = chat.model_payload([{'role': 'system', 'content': 'fixture', '_evidence_package': package.model_dump(mode='json')}])
    assert not any(tool['function']['name'] == 'submit_answer' for tool in payload['tools'])
    assert any(tool['function']['name'] == 'recommend_tools' for tool in payload['tools'])


def test_semantic_routing_prompt_does_not_present_lexical_fallback_as_answer(client, monkeypatch):
    seen = script(monkeypatch, calls(('respond_conversationally', {'intent': 'help', 'text': 'Tell me what is taking time in your business.'})))
    send(client, message='Help me choose something useful')
    system = seen[0][0]['content']
    assert 'No catalog lookup has been performed' in system
    assert 'initial_evidence_package:' not in system
    assert 'Explore: ' not in system


def test_routing_excerpts_are_constrained_to_owner_text_and_private_metadata_stays_local(client, monkeypatch):
    seen = script(monkeypatch,
                  calls(('update_memory', {'trade': 'hvac'})),
                  calls(('recommend_tools', {'problem_id': 'missed_calls', 'task_text': 'People hang up before we can speak'})),
                  calls(('submit_answer', {'claim_ids': []})))
    send(client, message='People hang up before we can speak')
    payload = chat.model_payload(seen[0])
    schema = next(tool['function']['parameters'] for tool in payload['tools'] if tool['function']['name'] == 'recommend_tools')
    assert schema['properties']['task_text']['enum'] == ['People hang up before we can speak']
    assert 'task_text' in schema['required']
    assert all('_owner_excerpts' not in message and '_evidence_package' not in message for message in payload['messages'])
    result = __import__('json').loads(seen[1][-1]['content'])
    assert 'routing_required' in result
    assert 'evidence_package' not in result


def test_two_explicit_needs_are_not_treated_as_an_unresolved_single_choice(client, monkeypatch):
    script(monkeypatch,
           calls(('recommend_tools', {'problem_id': 'bookkeeping', 'task_text': 'My books are behind'}),
                 ('recommend_tools', {'problem_id': 'missed_calls', 'task_text': 'calls go unanswered'})),
           calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message='My books are behind and calls go unanswered', profile={'trade': 'hvac'})
    assert {event['problem_id'] for event in events if event['type'] == 'recommendation'} == {'bookkeeping', 'missed_calls'}
    assert any(event.get('validation') == 'validated' for event in events)
