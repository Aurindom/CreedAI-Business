import json
from datetime import datetime, timezone
from uuid import UUID
import pytest
from app import chat
from conftest import account_header


def setup_model(monkeypatch, seen):
    monkeypatch.setattr(chat, 'chat_available', lambda: True)
    async def fake(messages):
        seen.append(chat.model_payload(messages))
        return {'choices': [{'message': {'content': '', 'tool_calls': [{'id': 'fixture', 'type': 'function',
                     'function': {'name': 'submit_answer', 'arguments': '{"claim_ids":[]}'}}]}}],
                'usage': {'cost': 0.001, 'prompt_tokens': 1000, 'completion_tokens': 50}}
    monkeypatch.setattr(chat, 'call_model', fake)


BODY = {'conversation_id': 'fixture', 'message': 'I need bookkeeping help', 'profile': {'trade': 'hvac'}}


def frames(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]


def test_penny_uses_verified_subject_not_browser_identity_and_never_sends_credentials_to_model(client, monkeypatch):
    seen = []
    setup_model(monkeypatch, seen)
    response = client.post('/api/chat', headers=account_header(1, 1), json={**BODY, 'user_id': str(UUID(int=2)), '_principal': {'user_id': str(UUID(int=2))}})
    events = frames(response)
    assert events[0]['auth_mode'] == 'account'
    assert events[0]['account_id'] == str(UUID(int=1))
    assert any(event.get('validation') == 'validated' for event in events)
    assert str(UUID(int=1)) not in json.dumps(seen)
    assert account_header(1, 1)['Authorization'] not in json.dumps(seen)


def test_guest_penny_has_no_account_authority(client, monkeypatch):
    setup_model(monkeypatch, [])
    events = frames(client.post('/api/chat', json=BODY))
    assert events[0]['auth_mode'] == 'guest'
    assert events[0]['account_id'] is None
    assert any(event.get('validation') == 'validated' for event in events)


def test_invalid_bearer_is_not_reinterpreted_as_guest(client, monkeypatch):
    seen = []
    setup_model(monkeypatch, seen)
    assert client.post('/api/chat', headers={'Authorization': 'Bearer forged'}, json=BODY).status_code == 401
    assert seen == []


def test_logout_during_generation_prevents_answer_delivery(client, monkeypatch):
    setup_model(monkeypatch, [])
    original = chat.call_model
    async def revoke_then_reply(messages):
        with client.app.state.lock, client.app.state.conn:
            client.app.state.conn.execute('INSERT INTO revoked_auth_session VALUES(?,?,?)',
                (str(UUID(int=1)), str(UUID(int=1)), datetime.now(timezone.utc).isoformat()))
        return await original(messages)
    monkeypatch.setattr(chat, 'call_model', revoke_then_reply)
    events = frames(client.post('/api/chat', headers=account_header(), json=BODY))
    assert any(event.get('code') == 'session_expired' for event in events)
    assert not any(event['type'] == 'message_delta' for event in events)
