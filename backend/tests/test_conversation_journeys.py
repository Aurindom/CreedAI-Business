"""Multi-turn state, semantic follow-ups and isolation; no paid provider calls."""
import json
import pytest

from app import chat, public_mcp
from app.conversation_state import business_description, comparison_package, small_answer
from app.agent.guard import LeakGuard
from app.penny_conversation import validate_conversation
from app.schemas import BusinessProfile
from test_chat_hermes import FakeHermes, answer, db_path, frames, hermes


@pytest.fixture
def public_reads(monkeypatch):
    monkeypatch.setenv('CHAT_CATALOG_FAST_PATH', 'true')
    monkeypatch.setenv('PUBLIC_MCP_URL', 'http://actions:8000/mcp')
    monkeypatch.setenv('PUBLIC_MCP_TOKEN', 'test-public-mcp-token')
    reads = []
    async def rpc(http, config, number, method, params):
        args = params['arguments']
        reads.append(args['tool_id'])
        public_mcp.lookup(db_path(), args['tool_id'], args['operation'])
        return {'isError': False}
    monkeypatch.setattr(chat.readiness, '_rpc', rpc)
    return reads


def turn(client, message, memory=None, history=None):
    response = client.post('/api/chat', json={'conversation_id': 'journey', 'message': message,
        'memory': memory or {}, 'history': history or []})
    assert response.status_code == 200, response.text
    events = frames(response)
    assert events[-1] == {'type': 'done'}
    assert not [event for event in events if event['type'] == 'error'], events
    updates = [event['memory'] for event in events if event['type'] == 'memory']
    return events, updates[-1] if updates else memory or {}


@pytest.mark.parametrize('business', ['sex toy business', 'mobile bicycle repair studio', 'ceramic restoration company', 'specialty mushroom farm'])
def test_unfamiliar_business_recall_compare_and_price_followup(client, public_reads, business):
    events, memory = turn(client, f'I own a {business}, I keep missing calls')
    assert memory['business_description'] == business
    assert memory['active_task_ids'] and len(memory['last_tool_ids']) >= 2
    before = set(memory['last_tool_ids'])
    events, memory = turn(client, 'do you not remember my business?', memory)
    assert business in ''.join(event.get('text', '') for event in events)
    events, memory = turn(client, 'compare all the options', memory)
    assert memory['pending_question'] == 'comparison'
    assert 'price' in ''.join(event.get('text', '') for event in events)
    public_reads.clear()
    events, memory = turn(client, 'overall cost', memory)
    assert set(public_reads) == before
    assert memory['comparison_criterion'] == 'cost'
    assert all(event.get('validation') != 'fallback' for event in events)
    assert 'Comparing these alternatives' in ''.join(event.get('text', '') for event in events)
    events, memory = turn(client, 'hello', memory)
    assert memory['business_description'] == business


def test_failure_preserves_owner_state_and_recoverable_shortlist(client, public_reads, monkeypatch):
    _, memory = turn(client, 'I own a kite repair studio, I keep missing calls')
    original = dict(memory)
    async def fail(*args):
        return None
    monkeypatch.setattr(chat.readiness, '_rpc', fail)
    response = client.post('/api/chat', json={'conversation_id': 'journey', 'message': 'compare by price', 'memory': memory})
    events = frames(response)
    assert any(event.get('code') == 'tool_unavailable' for event in events)
    assert not any(event['type'] == 'memory' and not event['memory']['last_tool_ids'] for event in events)
    events, recalled = turn(client, 'remember my business?', original)
    assert recalled['business_description'] == 'kite repair studio'
    assert recalled['last_tool_ids'] == original['last_tool_ids']


def test_semantic_comparison_action_uses_stored_shortlist(client, hermes, public_reads):
    _, memory = turn(client, 'I own a lamp repair studio, I keep missing calls')
    message = 'Could you weigh those choices against one another?'
    raw = {'claim_ids': [], 'followup_id': None, 'routes': None, 'trade': None, 'trade_text': None,
           'conversation_intent': None, 'reply_id': None,
           'action': {'kind': 'compare', 'criterion': None, 'owner_text': message}}
    hermes(FakeHermes(lambda package: answer(package, tools=(), output=json.dumps(raw))))
    _, after = turn(client, message, memory)
    assert after['pending_question'] == 'comparison'
    assert after['last_tool_ids'] == memory['last_tool_ids']


def test_changed_business_and_new_chat_do_not_reuse_another_context(client, public_reads):
    _, memory = turn(client, 'I own a bakery, I need help with bookkeeping')
    _, changed = turn(client, 'Actually I run a kite repair studio', memory)
    assert changed['business_description'] == 'kite repair studio'
    assert changed['last_tool_ids'] == []
    events, fresh = turn(client, 'remember my business?')
    assert not fresh.get('business_description')
    assert 'do not have your business type' in ''.join(event.get('text', '') for event in events)


def test_wrong_greeting_cannot_pass_as_a_business_answer(catalog):
    reply = validate_conversation({'intent': 'greeting', 'text': "Hi! I'm Arkadio. How can I help today?"},
        catalog, LeakGuard([]), 'What businesses can you help me with today?')
    assert reply.reason == 'conversation_intent_mismatch'


@pytest.mark.parametrize('message,result', [('2+2', '4.'), ('what is 12 / 3?', '4.'), ('(2+3)*4', '20.')])
def test_bounded_arithmetic(client, message, result):
    events, _ = turn(client, message)
    assert ''.join(event.get('text', '') for event in events).startswith(result)


def test_arithmetic_is_not_python_execution():
    assert small_answer('__import__("os").system("anything")') is None
    assert small_answer('2**100000') is None
    assert business_description('hello', pending=True) is None
    assert business_description('We run three vans and I hate paperwork.') is None
    assert business_description('2+2', pending=True) is None


def test_comparison_requires_receipts_for_all_six_shortlisted_tools(client, public_reads):
    catalog = client.app.state.catalog
    ids = [tool.id for tool in catalog.tools if tool.status != 'rejected'][:6]
    events, _ = turn(client, 'compare by plan', {'business_description': 'repair studio',
        'active_task_ids': ['missed_calls'], 'last_tool_ids': ids})
    assert set(public_reads) == set(ids)
    assert not any(event.get('validation') == 'fallback' for event in events)


def test_pricing_a_named_new_tool_does_not_reuse_old_comparison(catalog):
    from app.conversation_state import local_action
    memory = chat.ChatMemory(last_tool_ids=['voice', 'solo'], active_task_ids=['calls'])
    assert local_action('What is the price of QuickBooks?', memory) is None
    assert local_action("Do not compare anything", memory) is None
