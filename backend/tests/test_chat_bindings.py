import copy
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app import chat
from app.agent import bindings
from conftest import account_header

BODY = {'conversation_id': 'fixture', 'message': 'Save my plan please', 'profile': {'trade': 'hvac'}}
PLAN = {'problem_ids': ['missed_calls'], 'tool_ids': ['jobber']}
ANSWER = ('answer', 'submit_answer', {'claim_ids': []})


def script(monkeypatch, rounds, seen, during=None):
    """Plays one list of tool calls per model round, then submits an answer. `during` runs inside the first call."""
    monkeypatch.setattr(chat, 'chat_available', lambda: True)
    queue = list(rounds)

    async def fake(messages):
        seen.append(copy.deepcopy(messages))
        if during and len(seen) == 1:
            during()
        calls = queue.pop(0) if queue else [ANSWER]
        return {'choices': [{'message': {'content': '', 'tool_calls': [
                    {'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}
                    for call_id, name, args in calls]}}],
                'usage': {'cost': 0.001, 'prompt_tokens': 1000, 'completion_tokens': 50}}
    monkeypatch.setattr(chat, 'call_model', fake)


def frames(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]


def tool_results(seen):
    return {message['tool_call_id']: json.loads(message['content'])
            for messages in seen for message in messages if message.get('role') == 'tool'}


def rows(client, sql, *args):
    with client.app.state.lock:
        return client.app.state.conn.execute(sql, args).fetchall()


def revoke(client, user=1, session=1):
    with client.app.state.lock, client.app.state.conn:
        client.app.state.conn.execute('INSERT INTO revoked_auth_session VALUES(?,?,?)',
                                      (str(UUID(int=session)), str(UUID(int=user)), datetime.now(timezone.utc).isoformat()))


def test_signed_in_owner_saves_a_plan_through_chat_into_their_own_workspace(client, monkeypatch):
    seen = []
    script(monkeypatch, [[('call-1', 'save_plan', PLAN)]], seen)
    events = frames(client.post('/api/chat', headers=account_header(1, 1), json=BODY))
    result = tool_results(seen)['call-1']
    assert result['outcome'] == 'succeeded' and result['saved']
    assert any(event.get('validation') == 'validated' for event in events)
    assert [plan['id'] for plan in client.get('/api/plans', headers=account_header(1, 1)).json()] == [result['saved']]
    assert client.get('/api/plans', headers=account_header(2, 2)).json() == []
    assert rows(client, 'SELECT user_id FROM agent_run') == [(str(UUID(int=1)),)]
    assert rows(client, 'SELECT call_id, outcome FROM action_receipt WHERE used_at IS NOT NULL') == [('call-1', 'succeeded')]


def test_two_accounts_with_the_same_conversation_id_save_into_separate_workspaces(client, monkeypatch):
    seen = []
    script(monkeypatch, [[('call-1', 'save_plan', PLAN)], [ANSWER], [('call-1', 'save_plan', PLAN)]], seen)
    client.post('/api/chat', headers=account_header(1, 1), json=BODY)
    client.post('/api/chat', headers=account_header(2, 2), json=BODY)
    alice = client.get('/api/plans', headers=account_header(1, 1)).json()
    bob = client.get('/api/plans', headers=account_header(2, 2)).json()
    assert len(alice) == 1 and len(bob) == 1 and alice[0]['id'] != bob[0]['id']
    assert len({row[0] for row in rows(client, 'SELECT business_id FROM agent_run')}) == 2


def test_identity_fields_from_the_model_are_rejected_before_anything_runs(client, monkeypatch):
    seen = []
    script(monkeypatch, [[('forged-save', 'save_plan', {**PLAN, 'owner_hash': 'someone-else'}),
                          ('forged-read', 'recommend_tools', {'task': 'missed_calls', 'business_id': 'other'})]], seen)
    client.post('/api/chat', headers=account_header(1, 1), json=BODY)
    results = tool_results(seen)
    assert 'come from the server' in results['forged-save']['error']
    assert 'come from the server' in results['forged-read']['error']
    assert rows(client, 'SELECT COUNT(*) FROM action_receipt') == [(0,)]
    assert client.get('/api/plans', headers=account_header(1, 1)).json() == []


def test_browser_supplied_identity_does_not_change_whose_workspace_is_used(client, monkeypatch):
    seen = []
    script(monkeypatch, [[('call-1', 'save_plan', PLAN)]], seen)
    forged = {**BODY, 'user_id': str(UUID(int=2)), 'owner_hash': 'x', '_principal': {'user_id': str(UUID(int=2))}}
    client.post('/api/chat', headers=account_header(1, 1), json=forged)
    assert len(client.get('/api/plans', headers=account_header(1, 1)).json()) == 1
    assert client.get('/api/plans', headers=account_header(2, 2)).json() == []


def test_guest_keeps_public_answers_but_cannot_save(client, monkeypatch):
    seen = []
    script(monkeypatch, [[('guest-save', 'save_plan', PLAN)]], seen)
    events = frames(client.post('/api/chat', json=BODY))
    assert events[0]['auth_mode'] == 'guest'
    assert 'signed-in account' in tool_results(seen)['guest-save']['error']
    assert any(event.get('validation') == 'validated' for event in events)
    assert rows(client, 'SELECT COUNT(*) FROM agent_run') == [(0,)]
    assert rows(client, 'SELECT COUNT(*) FROM adoption_plan') == [(0,)]


def test_a_repeated_call_id_in_one_run_cannot_save_twice(client, monkeypatch):
    seen = []
    script(monkeypatch, [[('call-1', 'save_plan', PLAN)], [('call-1', 'save_plan', PLAN)]], seen)
    client.post('/api/chat', headers=account_header(1, 1), json=BODY)
    results = [json.loads(message['content']) for message in seen[-1] if message.get('role') == 'tool']
    assert results[0]['outcome'] == 'succeeded'
    assert 'already ran' in results[1]['error']
    assert len(client.get('/api/plans', headers=account_header(1, 1)).json()) == 1


def test_failed_save_is_reported_as_failed_not_success(client, monkeypatch):
    seen = []
    script(monkeypatch, [[('bad', 'save_plan', {'problem_ids': ['missed_calls'], 'tool_ids': ['no_such_tool']})]], seen)
    client.post('/api/chat', headers=account_header(1, 1), json=BODY)
    result = tool_results(seen)['bad']
    assert result['outcome'] == 'failed' and 'saved' not in result
    assert rows(client, 'SELECT outcome FROM action_receipt') == [('failed',)]
    assert client.get('/api/plans', headers=account_header(1, 1)).json() == []


def test_logged_out_session_gets_no_model_call_and_no_private_action(client, monkeypatch):
    seen = []
    script(monkeypatch, [[('call-1', 'save_plan', PLAN)]], seen)
    revoke(client)
    response = client.post('/api/chat', headers=account_header(1, 1), json=BODY)
    assert response.status_code == 401 or any(event.get('code') == 'session_expired' for event in frames(response))
    assert seen == []
    assert rows(client, 'SELECT COUNT(*) FROM adoption_plan') == [(0,)]


def test_logout_during_the_run_blocks_the_save_and_the_answer(client, monkeypatch):
    seen = []
    script(monkeypatch, [[('call-1', 'save_plan', PLAN)]], seen, during=lambda: revoke(client))
    events = frames(client.post('/api/chat', headers=account_header(1, 1), json=BODY))
    assert any(event.get('code') == 'session_expired' for event in events)
    assert not any(event['type'] == 'message_delta' for event in events)
    assert rows(client, 'SELECT COUNT(*) FROM action_receipt') == [(0,)]
    assert client.get('/api/plans', headers=account_header(1, 2)).json() == []


def test_conversation_past_its_recovery_window_is_closed(client, monkeypatch):
    seen = []
    script(monkeypatch, [], seen)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with client.app.state.lock, client.app.state.conn:
        client.app.state.conn.execute('INSERT INTO chat_conversation VALUES(?,?,?,?,?)',
                                      (str(UUID(int=1)), 'fixture', str(UUID(int=1)), past, past))
    events = frames(client.post('/api/chat', headers=account_header(1, 1), json=BODY))
    assert events[0]['code'] == 'conversation_closed'
    assert seen == []


def test_unlisted_action_is_refused(client, monkeypatch):
    seen = []
    script(monkeypatch, [[('shell', 'run_shell', {'cmd': 'ls'})]], seen)
    client.post('/api/chat', headers=account_header(1, 1), json=BODY)
    assert tool_results(seen)['shell']['error'] == "That action isn't available."


def test_the_live_chat_route_calls_the_binding_checks(client, monkeypatch):
    seen, checked = [], []
    original = bindings.authorize
    monkeypatch.setattr(bindings, 'authorize', lambda binding, action, arguments: checked.append(action) or original(binding, action, arguments))
    script(monkeypatch, [[('details', 'get_tool_details', {'tool_id': 'jobber'}), ('call-1', 'save_plan', PLAN)]], seen)
    client.post('/api/chat', headers=account_header(1, 1), json=BODY)
    assert checked[:2] == ['get_tool_details', 'save_plan'] and 'submit_answer' in checked


def test_logout_while_the_model_is_answering_blocks_the_final_answer(client, monkeypatch):
    seen = []
    script(monkeypatch, [], seen, during=lambda: revoke(client))
    events = frames(client.post('/api/chat', headers=account_header(1, 1), json=BODY))
    assert any(event.get('code') == 'session_expired' for event in events)
    assert not any(event['type'] == 'message_delta' for event in events)
    assert len(seen) == 1


def test_guest_answer_is_still_delivered_after_an_account_logs_out(client, monkeypatch):
    seen = []
    script(monkeypatch, [], seen, during=lambda: revoke(client))
    events = frames(client.post('/api/chat', json=BODY))
    assert any(event['type'] == 'message_delta' for event in events)
