"""Vague requests get a question, not a guessed tool list.

Reported: after the background questions Penny said "The catalog search did not work", and
"i want an AI tool" jumped straight to website-chat tools for a bakery.
"""
from app.penny_grounding import is_generic_request, suggested_task_ids
from test_chat import calls, client, kinds, script, send  # noqa: F401  (client is a fixture)

BAKERY_MEMORY = {'trade': 'bakery', 'owned': [], 'ruled_out': [], 'budget_monthly_usd': 0,
                 'background_done': True, 'active_task_ids': [], 'pending_question': None, 'pending_task_ids': []}
BUDGET_QUESTION = 'What can you add to your monthly software bill?'


def clarify_events(events):
    return [event for event in events if event['type'] == 'clarify']


def all_text(events):
    return ' '.join(str(event) for event in events)


def test_generic_requests_are_recognised():
    for text in ['i want an AI tool', 'I need help choosing AI', 'can you recommend some software?',
                 'Which AI tools should I use for my business', 'help me find an app', 'I want to use AI']:
        assert is_generic_request(text), text
    for text in ['I keep missing calls', 'my books are behind', 'yes', 'Bakery', 'I want an AI tool for invoicing',
                 'we need a chatbot on our website', 'hi', 'Help me get started', 'what can you help me with?',
                 'help me please', 'Help me decide']:
        assert not is_generic_request(text), text


def test_suggestions_fit_the_business(client):
    catalog = client.app.state.catalog
    bakery = suggested_task_ids(catalog, 'bakery', 12)
    assert set(bakery[:2]) == {'staff_scheduling', 'point_of_sale'}, 'tasks listed for bakeries come first'
    assert 'website_chat_leads' not in bakery, 'tasks only for other businesses are left out'
    assert suggested_task_ids(catalog, None, 3) == [card.id for card in catalog.problem_cards[:3]]


def test_task_question_without_choices_still_asks_instead_of_failing(client, monkeypatch):
    # After the background questions the model asks "what do you need help with" but forgets the choices.
    script(monkeypatch, calls(('ask_owner', {'question_id': 'task'})))
    events = send(client, message='$0 added', memory={**BAKERY_MEMORY, 'pending_question': 'budget'},
                  history=[{'role': 'assistant', 'text': BUDGET_QUESTION}])
    assert 'catalog search did not work' not in all_text(events)
    asked = clarify_events(events)
    assert asked and asked[0]['question'] == 'What would you like help with?'
    assert set(asked[0]['choices'][:2]) == {'Building the staff schedule takes too long', 'The register does not do enough'}


def test_vague_request_gets_task_choices_for_the_business_without_a_model_call(client, monkeypatch):
    seen = script(monkeypatch)  # any model call would fail: the queue is empty
    events = send(client, message='i want an AI tool', memory=BAKERY_MEMORY)
    assert seen == []
    assert not [event for event in events if event.get('surface') == 'recommendation']
    assert 'Website visitors leave without asking' not in all_text(events)
    asked = clarify_events(events)
    assert asked and asked[0]['question'] == 'What would you like help with?'
    assert 'Building the staff schedule takes too long' in asked[0]['choices']
    memory = [event['memory'] for event in events if event['type'] == 'memory'][-1]
    assert memory['pending_question'] == 'task' and 'staff_scheduling' in memory['pending_task_ids']
    assert kinds(events)[-1] == 'done'


def test_vague_request_from_a_new_owner_starts_the_background_questions(client, monkeypatch):
    seen = script(monkeypatch)
    events = send(client, message='I need help choosing AI')
    assert seen == []
    asked = clarify_events(events)
    assert asked and asked[0]['question'] == 'What kind of business do you run?'


def test_picking_a_suggested_task_then_shows_tools(client, monkeypatch):
    script(monkeypatch, calls(('recommend_tools', {'problem_id': 'staff_scheduling',
                                                   'task_text': 'Building the staff schedule takes too long'})),
           calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message='Building the staff schedule takes too long',
                  memory={**BAKERY_MEMORY, 'pending_question': 'task', 'pending_task_ids': ['staff_scheduling', 'point_of_sale', 'missed_calls']},
                  history=[{'role': 'user', 'text': 'i want an AI tool'}, {'role': 'assistant', 'text': 'What would you like help with?'}])
    assert [event for event in events if event.get('surface') == 'recommendation']


def test_specific_request_still_goes_straight_to_tools(client, monkeypatch):
    script(monkeypatch,
           calls(('recommend_tools', {'problem_id': 'missed_calls', 'task_text': 'I keep missing calls'})),
           calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message='I keep missing calls', memory=BAKERY_MEMORY)
    assert [event for event in events if event.get('surface') == 'recommendation']
    assert 'done' in kinds(events)


def test_a_rejected_question_never_reads_as_a_failed_catalog_search(client, monkeypatch):
    # Business unknown, so the choices can't be filled in; the model gives up instead of retrying.
    script(monkeypatch, calls(('ask_owner', {'question_id': 'task'})), calls(('submit_answer', {'claim_ids': []})))
    events = send(client, message='$0 added', memory={'pending_question': 'budget', 'background_done': True},
                  history=[{'role': 'assistant', 'text': BUDGET_QUESTION}])
    assert 'catalog search did not work' not in all_text(events)
    assert kinds(events)[-1] == 'done'


def test_suggestions_accept_the_business_name_the_page_sends(client):
    catalog = client.app.state.catalog
    assert suggested_task_ids(catalog, 'Bakery', 3) == suggested_task_ids(catalog, 'bakery', 3)


def test_a_rejected_request_logs_field_names_not_content(client, caplog):
    secret = 'my-private-note-123'
    response = client.post('/api/chat/validate', json={'conversation_id': 'c1', 'message': secret,
                                                       'memory': {'pending_task_ids': ['a', 'b', 'c', 'd']}})
    assert response.status_code == 422
    logged = ' '.join(record.getMessage() for record in caplog.records if record.name == 'app.requests')
    assert 'body.memory.pending_task_ids' in logged
    assert secret not in logged


def test_business_question_offers_other_and_survives_saved_history(client, monkeypatch):
    from app.schemas import MAX_QUESTION_CHOICES
    seen = script(monkeypatch)
    events = send(client, message='I need help choosing AI')
    asked = clarify_events(events)[0]
    assert asked['choices'][-2:] == ['Other', 'Skip these questions']
    assert len(asked['choices']) == MAX_QUESTION_CHOICES == 5
    surface = next(event for event in events if event['type'] == 'a2ui')
    assert surface['messages'][1]['updateComponents']['components'][0]['choices'] == asked['choices']
    assert seen == []


def test_memory_records_the_choices_shown_not_the_models_list(client, monkeypatch):
    # Reported: the model offered five tasks, the backend showed three, but memory kept all five,
    # so every later message was rejected for an over-long pending_task_ids.
    five = ['bookkeeping', 'invoicing', 'email_marketing', 'review_replies', 'missed_calls']
    script(monkeypatch, calls(('ask_owner', {'question_id': 'task', 'problem_ids': five})))
    events = send(client, message='No software yet', memory={**BAKERY_MEMORY, 'pending_question': 'software'},
                  history=[{'role': 'assistant', 'text': 'Which software do you already use?'}])
    asked = clarify_events(events)[0]
    memory = [event['memory'] for event in events if event['type'] == 'memory'][-1]
    assert len(memory['pending_task_ids']) <= 3
    titles = {card.id: card.title for card in client.app.state.catalog.problem_cards}
    assert [titles[pid] for pid in memory['pending_task_ids']] == asked['choices'][:-1]
    follow_up = client.post('/api/chat/validate', json={'conversation_id': 'c1', 'message': asked['choices'][0], 'memory': memory})
    assert follow_up.status_code == 200, 'the next message is accepted'


def test_memory_sent_to_the_browser_always_fits_its_limits():
    from app.chat import ChatMemory, _memory_event
    over = ChatMemory.model_construct(**{**ChatMemory().model_dump(), 'pending_task_ids': list('abcdef'), 'active_task_ids': list('abcdefgh')})
    memory = _memory_event(over)['memory']
    assert len(memory['pending_task_ids']) == 3 and len(memory['active_task_ids']) == 5
    ChatMemory.model_validate(memory)
