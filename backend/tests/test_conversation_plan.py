"""Fulfilment tests: real account service, changes between turns and contextual negatives.

Synthetic model outputs test interpretation/execution boundaries separately;
live held-out paraphrases are a separate release gate, not simulated here.
"""
import json
import pytest

from app import chat, conversation_plan as planner
from app.chat_history import ChatSnapshot
from app.conversation_state import business_description
from app.ownership import stated_ownership
from conftest import account_header
from test_conversation_journeys import public_reads  # noqa: F401
from test_chat_hermes import FakeHermes, answer, frames, hermes  # noqa: F401
from test_chat_history import history  # noqa: F401


MEMORY = {'business_description': 'kite repair studio', 'active_task_ids': ['invoicing'],
          'last_tool_ids': ['jobber', 'housecall_pro', 'lmn'], 'comparison_criterion': 'price'}


def turn(client, message, memory=None, user=None, history=None):
    response = client.post('/api/chat', headers=account_header(user) if user else {}, json={
        'conversation_id': 'plan-journey', 'message': message, 'memory': memory or MEMORY, 'history': history or [], 'ui_version': 3})
    assert response.status_code == 200
    events = frames(response)
    assert events[-1] == {'type': 'done'}
    assert not [event for event in events if event['type'] == 'error'], events
    state = [event['memory'] for event in events if event['type'] == 'memory']
    text = '\n'.join(event.get('text', '') for event in events if event['type'] == 'message_delta')
    return events, state[-1] if state else memory or MEMORY, text


def semantic(hermes, steps, **extra):
    raw = {'claim_ids': [], 'followup_id': None, 'routes': None, 'trade': None, 'trade_text': None,
           'business_text': None, 'action': None, 'conversation_intent': None, 'reply_id': None,
           'plan': {'steps': steps}, **extra}
    fake = FakeHermes(lambda package: answer(package, tools=(), output=json.dumps(raw)))
    hermes(fake)
    return fake


@pytest.mark.parametrize('message,needles', [
    ('what is this website about?', ['heart', 'history', 'compare']),
    ('How do I save tools as a favourite?', ['Sign in', 'heart', 'Favourite tools']),
    ('Where can I find my saved tools?', ['heart', 'Favourite tools']),
    ('How do I delete my history?', ['Delete history', '30 days', 'Guests']),
])
def test_app_help_answers_topic_without_old_business(client, public_reads, message, needles):
    _, state, text = turn(client, message)
    assert all(needle in text for needle in needles)
    assert state['business_description'] == MEMORY['business_description']
    assert not public_reads


def test_account_favourites_read_write_change_and_isolation(client, public_reads):
    _, state, text = turn(client, 'what are my fav tools?', user=1)
    assert 'no saved favourite' in text
    _, state, text = turn(client, 'Save Jobber to favourites', user=1)
    assert 'Saved Jobber' in text
    assert state['owned'] == []
    assert [row['tool_id'] for row in client.get('/api/favourites', headers=account_header(1)).json()] == ['jobber']
    _, _, text = turn(client, 'what are my fav tools?', user=2)
    assert 'no saved favourite' in text
    _, _, text = turn(client, 'Do you remember my business? What tools have I saved as favourites?', user=1)
    assert 'kite repair studio' in text and 'Jobber' in text
    client.put('/api/favourites/mailchimp', headers=account_header(1))
    _, _, text = turn(client, 'what are my fav tools?', user=1)
    assert 'Jobber' in text and 'Mailchimp' in text
    _, _, text = turn(client, 'Remove Jobber from favourites', user=1)
    assert 'Removed Jobber' in text
    _, _, text = turn(client, 'what are my fav tools?', user=1)
    assert 'Jobber' not in text and 'Mailchimp' in text


def test_guest_favourites_not_substituted_with_owned_tools(client, public_reads):
    _, _, text = turn(client, 'what are my fav tools?', {**MEMORY, 'owned': ['jobber']})
    assert 'Sign in' in text and 'Jobber' not in text


def test_ambiguous_save_asks_without_mutation(client, public_reads):
    _, state, text = turn(client, 'Save it to favourites', user=1)
    assert 'Which tool' in text
    assert client.get('/api/favourites', headers=account_header(1)).json() == []
    _, state, text = turn(client, 'Jobber', state, user=1)
    assert 'Saved Jobber' in text and state['pending_favourite_action'] is None


def test_explicit_ordinal_save_uses_own_shortlist(client, public_reads):
    _, _, text = turn(client, 'Save the second option to favourites', user=1)
    assert 'Housecall Pro' in text
    assert [row['tool_id'] for row in client.get('/api/favourites', headers=account_header(1)).json()] == ['housecall_pro']


def test_format_followup_reuses_criterion_and_table_history(client, public_reads):
    events, state, text = turn(client, 'Give me a table of comparison')
    table = next(event for event in events if event.get('surface') == 'table')
    component = table['messages'][1]['updateComponents']['components'][0]
    assert component['criterion'] == 'price'
    assert [row['tool_id'] for row in component['rows']] == MEMORY['last_tool_ids']
    assert 'Jobber:' not in text  # No duplicated paragraph response.
    assert set(public_reads) == set(MEMORY['last_tool_ids'])
    ChatSnapshot.model_validate({'conversationId': 'plan-journey', 'memory': state, 'messages': [
        {'id': 'table', 'kind': 'a2ui', 'surface': 'table', 'text': table['message'], 'protocol': table['messages']}]})


@pytest.mark.parametrize('negative', ['exclude', 'remove', 'do not list', 'leave out', 'without'])
def test_negative_comparison_constraints_never_become_positive_selection(client, public_reads, negative):
    events, state, text = turn(client, f'Compare prices but {negative} Jobber')
    assert 'jobber' not in public_reads
    assert set(public_reads) == {'housecall_pro', 'lmn'}
    assert 'Jobber:' not in text and 'one option' not in text
    assert state['comparison_excluded_ids'] == ['jobber']
    public_reads.clear()
    turn(client, 'Give me a table', state)
    assert 'jobber' not in public_reads


def test_forgetting_survives_history_and_page_profile(client, public_reads):
    old_history = [{'role': 'user', 'text': 'I own a kite repair studio'}]
    _, state, text = turn(client, 'Forget my business', history=old_history)
    assert state['business_forgotten'] and state['business_description'] is None
    assert state['last_tool_ids'] == []
    assert chat._effective_profile(client.app.state.catalog, chat.BusinessProfile(trade='hvac'), chat.ChatMemory(**state)).trade is None
    _, state, text = turn(client, 'Do you remember my business?', state, history=old_history)
    assert 'do not have your business' in text and 'kite repair studio' not in text
    _, state, text = turn(client, 'I own an insect protein farm', state)
    assert state['business_description'] == 'insect protein farm' and not state['business_forgotten']


@pytest.mark.parametrize('prefix', ['Imagine I run a bakery.', 'If I run a bakery, what would change?',
                                   'My competitor says "I run a bakery".'])
def test_hypothetical_and_quoted_business_never_replace_confirmed_owner(client, public_reads, hermes, prefix):
    message = prefix + ' Do you remember my business?'
    semantic(hermes, [{'kind': 'recall', 'owner_text': 'Do you remember my business?'}])
    _, state, text = turn(client, message)
    assert state['business_description'] == 'kite repair studio' and 'kite repair studio' in text


@pytest.mark.parametrize('message', ['I have Jobber saved as a favourite', 'My competitor uses Jobber',
    'I used Jobber years ago', 'I have Jobber saved as a favourite but I do not subscribe',
    'If I use Jobber, will it help?', 'My friend says "we use Jobber"'])
def test_bookmarks_past_tense_third_parties_are_not_owned(client, message):
    assert stated_ownership(client.app.state.catalog, message) == []


def test_semantic_plan_handles_unseen_app_help_and_mixed_intents(client, public_reads, hermes):
    client.put('/api/favourites/jobber', headers=account_header(1))
    message = 'Remind me what I run, show my bookmarks, then explain where this site keeps conversations.'
    semantic(hermes, [
        {'kind': 'recall', 'owner_text': 'Remind me what I run'},
        {'kind': 'favourites_list', 'owner_text': 'show my bookmarks'},
        {'kind': 'help', 'topic': 'history', 'owner_text': 'explain where this site keeps conversations'},
    ])
    _, _, text = turn(client, message, user=1)
    assert all(value in text for value in ('kite repair studio', 'Jobber', 'Past conversations'))


def test_how_to_and_assertion_never_authorize_favourite_mutation(client, public_reads, hermes):
    message = 'How would I bookmark Jobber?'
    semantic(hermes, [{'kind': 'favourites_save', 'owner_text': message, 'tool_ids': ['jobber']}])
    _, _, text = turn(client, message, user=1)
    assert 'Saved Jobber' not in text
    assert client.get('/api/favourites', headers=account_header(1)).json() == []


def test_unknown_business_goal_and_followup_retained(client, public_reads, hermes):
    message = 'I own a floating sauna rental business. How do I attract customers?'
    semantic(hermes, [{'kind': 'clarify', 'topic': 'acquisition', 'owner_text': 'How do I attract customers?'}])
    _, state, text = turn(client, message)
    assert state['business_description'] == 'floating sauna rental business'
    assert state['business_goal'] == 'attract customers'
    assert 'floating sauna rental business' in text and 'search' not in text
    assert state['pending_question'] == 'task' and 2 <= len(state['pending_task_ids']) <= 3


def test_incomplete_compound_request_does_not_short_circuit(client):
    assert planner.local_plan('Do you remember my business? Also help me choose the next move.', chat.ChatMemory(**MEMORY), client.app.state.catalog) is None


def test_business_subject_split_preserves_noun_phrase():
    assert business_description('I run a kite repair studio and handle urgent orders') == 'kite repair studio'


def test_strict_plan_schema_requires_all_fields():
    schema = planner.strict_schema()
    item = schema['properties']['steps']['items']
    assert set(item['required']) == set(item['properties'])
    assert '$defs' not in schema and '$ref' not in json.dumps(schema)


def test_hypothetical_assumption_is_separate_and_followup_can_return_to_owner(client, public_reads, hermes):
    message = 'Imagine I run a bakery. How would I get customers?'
    semantic(hermes, [{'kind': 'clarify', 'topic': 'acquisition', 'owner_text': message,
                      'context_mode': 'scenario', 'assumed_business': 'bakery'}], business_text='bakery')
    _, state, text = turn(client, message)
    assert 'Assuming' in text and 'bakery' in text
    assert state['business_description'] == 'kite repair studio' and state['scenario_business'] == 'bakery'
    _, _, text = turn(client, 'Do you remember my business?', state)
    assert 'kite repair studio' in text and 'bakery' not in text


def test_semantic_format_cannot_override_existing_price_basis(client, public_reads, hermes):
    message = 'Could you lay those choices out in a table instead?'
    semantic(hermes, [{'kind': 'compare', 'owner_text': message, 'criterion': 'fit', 'presentation': 'table'}])
    events, state, _ = turn(client, message)
    table = next(event for event in events if event.get('surface') == 'table')
    assert state['comparison_criterion'] == table['messages'][1]['updateComponents']['components'][0]['criterion'] == 'price'


def test_app_how_to_does_not_replace_business_goal(client, public_reads, hermes):
    memory = {**MEMORY, 'business_goal': 'attract customers'}
    _, state, _ = turn(client, 'How do I save tools as a favourite?', memory)
    assert state['business_goal'] == 'attract customers'
    message = 'How can I keep something here to look at later?'
    semantic(hermes, [{'kind': 'help', 'topic': 'favourites', 'owner_text': message}])
    _, state, _ = turn(client, message, state)
    assert state['business_goal'] == 'attract customers'


def test_scenario_recommendation_keeps_confirmed_owner_goal(client, public_reads, hermes):
    message = 'Imagine I run a bakery. I need help with bookkeeping'
    semantic(hermes, [{'kind': 'recommend', 'owner_text': 'I need help with bookkeeping',
                      'problem_ids': ['bookkeeping'], 'context_mode': 'scenario', 'assumed_business': 'bakery'}])
    events, state, _ = turn(client, message, {**MEMORY, 'business_goal': 'reduce phone interruptions'})
    assert any(event.get('surface') == 'recommendation' for event in events)
    assert state['business_goal'] == 'reduce phone interruptions'
    assert state['business_description'] == 'kite repair studio'


def test_failed_favourite_read_is_not_empty_list(client, public_reads, monkeypatch):
    import sqlite3
    from app import favourites
    def failed(*args, **kwargs):
        raise sqlite3.OperationalError('synthetic failure')
    monkeypatch.setattr(favourites, 'account_tools', failed)
    _, _, text = turn(client, 'what are my fav tools?', user=1)
    assert 'could not confirm' in text and 'no saved favourite' not in text


def test_forgotten_context_is_not_healed_when_loading_account_history(client, history):
    snapshot = {'conversationId': 'forgotten-history', 'memory': {'business_forgotten': True},
                'messages': [{'id': 'business', 'kind': 'user', 'text': 'I own a bakery'}]}
    assert client.put('/api/chat/history', headers=account_header(1), json=snapshot).status_code == 204
    saved = client.get('/api/chat/history', headers=account_header(1)).json()
    assert saved['memory']['business_description'] is None


def test_v3_gateway_has_plan_without_legacy_single_reply_escape_hatch():
    from app.model_gateway import _pinned
    body = _pinned({'messages': [{'role': 'system', 'content': 'penny_hermes_selection_v1\nconversation_state_v2\nconversation_plan_v3'}]})
    properties = body['response_format']['json_schema']['schema']['properties']
    assert 'plan' in properties
    assert properties['plan']['type'] == 'object'
    assert properties['action'] == properties['reply_id'] == properties['conversation_intent'] == {'type': 'null'}
    assert properties['routes'] == properties['trade'] == properties['trade_text'] == {'type': 'null'}
    old = _pinned({'messages': [{'role': 'system', 'content': 'penny_hermes_selection_v1\nconversation_state_v2'}]})
    assert 'plan' not in old['response_format']['json_schema']['schema']['properties']


def test_catalog_keyword_does_not_swallow_another_requested_action(client, public_reads, hermes):
    message = 'My books are behind. What tools have I saved as favourites?'
    semantic(hermes, [{'kind': 'recommend', 'owner_text': 'My books are behind', 'problem_ids': ['bookkeeping']},
                      {'kind': 'favourites_list', 'owner_text': 'What tools have I saved as favourites?'}])
    client.put('/api/favourites/mailchimp', headers=account_header(1))
    events, _, text = turn(client, message, user=1)
    assert any(event.get('surface') == 'recommendation' for event in events)
    assert 'Mailchimp' in text and 'favourite' in text


def test_older_ui_gets_readable_table_without_unsupported_component(client, public_reads):
    response = client.post('/api/chat', json={'conversation_id': 'old-client', 'message': 'Give me a comparison table', 'memory': MEMORY})
    events = frames(response)
    assert not any(event.get('surface') == 'table' for event in events)
    assert 'Tool | Required plan | Entry price | Added cost' in '\n'.join(event.get('text', '') for event in events)


def test_ambiguous_semantic_write_can_be_confirmed_without_repeating_tool_name(client, public_reads, hermes):
    message = 'Keep Jobber in the ones I have saved here'
    semantic(hermes, [{'kind': 'favourites_save', 'owner_text': message, 'tool_ids': ['jobber']}])
    _, state, text = turn(client, message, user=1)
    assert 'Do you want me to save Jobber' in text
    assert client.get('/api/favourites', headers=account_header(1)).json() == []
    _, state, text = turn(client, 'yes', state, user=1)
    assert 'Saved Jobber' in text and state['pending_favourite_ids'] == []
