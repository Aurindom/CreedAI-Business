"""Temporary history recovery, verified account isolation and immediate logout."""
from datetime import datetime, timedelta, timezone
import pytest
from app import chat, chat_history
from conftest import account_header


class FakeRedis:
    def __init__(self, clock):
        self.clock = clock
        self.items = {}

    async def get(self, key):
        value = self.items.get(key)
        return value[0] if value and value[1] > self.clock[0] else None

    async def set(self, key, value, ex):
        self.items[key] = (value, self.clock[0] + ex)

    async def expire(self, key, ex):
        if key in self.items:
            self.items[key] = (self.items[key][0], self.clock[0] + ex)
        return True

    async def aclose(self):
        pass


@pytest.fixture
def history(monkeypatch):
    clock = [0]
    cache = FakeRedis(clock)
    monkeypatch.setattr(chat_history, '_cache', lambda: cache)
    monkeypatch.setattr(chat_history, 'now', lambda: datetime(2026, 11, 7, tzinfo=timezone.utc) + timedelta(seconds=clock[0]))
    return clock, cache


SNAPSHOT = {'conversationId': 'conversation-1', 'messages': [{'id': 'm1', 'kind': 'user', 'text': 'Bakery workflow'}]}


def test_history_is_account_scoped_and_active_history_is_not_five_minute_cache(client, history):
    clock, _ = history
    alice, bob = account_header(1, 1), account_header(2, 2)
    assert client.put('/api/chat/history', json=SNAPSHOT, headers=alice).status_code == 204
    clock[0] = 600
    assert client.get('/api/chat/history', headers=alice).json()['conversationId'] == 'conversation-1'
    assert client.get('/api/chat/history', headers=bob).json() is None


def test_logout_blocks_old_session_and_same_account_can_restore_with_new_login(client, history):
    clock, _ = history
    old, fresh = account_header(1, 1), account_header(1, 2)
    client.put('/api/chat/history', json=SNAPSHOT, headers=old)
    assert client.post('/api/auth/logout', headers=old).json()['cache_grace_seconds'] == 300
    assert client.get('/api/chat/history', headers=old).status_code == 401
    assert client.put('/api/chat/history', json=SNAPSHOT, headers=old).status_code == 401
    clock[0] = 299
    assert client.get('/api/chat/history', headers=fresh).json()['messages'][0]['text'] == 'Bakery workflow'
    clock[0] = 601
    assert client.get('/api/chat/history', headers=fresh).json() is not None


def test_no_return_within_five_minutes_expires_conversation(client, history):
    clock, _ = history
    client.put('/api/chat/history', json=SNAPSHOT, headers=account_header(1, 1))
    client.post('/api/auth/logout', headers=account_header(1, 1))
    clock[0] = 300
    assert client.get('/api/chat/history', headers=account_header(1, 2)).json() is None
    assert client.put('/api/chat/history', json=SNAPSHOT, headers=account_header(1, 2)).status_code == 409


def test_logout_does_not_expire_another_active_session_conversation(client, history):
    clock, _ = history
    first, other = account_header(1, 1), account_header(1, 2)
    client.put('/api/chat/history', json=SNAPSHOT, headers=first)
    client.get('/api/chat/history', headers=other)
    client.post('/api/auth/logout', headers=first)
    clock[0] = 600
    assert client.get('/api/chat/history', headers=other).json() is not None


def test_guest_or_forged_token_cannot_read_account_history(client, history):
    assert client.get('/api/chat/history').status_code == 401
    assert client.get('/api/chat/history', headers={'Authorization': 'Bearer forged'}).status_code == 401


def test_same_conversation_id_for_different_users_is_isolated(client, history):
    a, b = account_header(1, 1), account_header(2, 2)
    client.put('/api/chat/history', json=SNAPSHOT, headers=a)
    second = {**SNAPSHOT, 'messages': [{'id': 'b', 'kind': 'user', 'text': 'Other business'}]}
    client.put('/api/chat/history', json=second, headers=b)
    assert client.get('/api/chat/history', headers=a).json()['messages'][0]['text'] == 'Bakery workflow'


def test_invalid_snapshot_and_owner_forgery_are_rejected(client, history):
    auth = account_header()
    assert client.put('/api/chat/history', json={**SNAPSHOT, 'user_id': 'somebody-else'}, headers=auth).status_code == 422
    bad = {**SNAPSHOT, 'messages': [{'id': 'm', 'kind': 'loading'}]}
    assert client.put('/api/chat/history', json=bad, headers=auth).status_code == 422


def test_cache_rejects_unapproved_a2ui_components(client, history):
    bad = {**SNAPSHOT, 'messages': [{'id': 'm', 'kind': 'a2ui', 'text': 'Buy', 'protocol': [
        {'version': 'v0.9', 'createSurface': {'surfaceId': 'penny-question-x', 'catalogId': chat_history.PENNY_CATALOG}},
        {'version': 'v0.9', 'updateComponents': {'surfaceId': 'penny-question-x', 'components': [{'id': 'root', 'component': 'ArbitraryScript'}]}}]}]}
    assert client.put('/api/chat/history', json=bad, headers=account_header()).status_code == 422


@pytest.mark.parametrize('surface,component,props,label', [
    ('text', 'PennyText', {'text': 'Checked catalog guidance'}, 'Checked catalog guidance'),
    ('sources', 'PennySources', {'items': [{'title': 'Vendor', 'url': 'https://example.com', 'checked': ''}]}, 'Sources for this tool'),
])
def test_valid_a2ui_surface_roundtrips(client, history, surface, component, props, label):
    event = chat._a2ui_event(surface, component, props, label)
    snapshot = {**SNAPSHOT, 'messages': [{'id': 'm', 'kind': 'a2ui', 'surface': surface, 'text': label, 'protocol': event['messages']}]}
    assert client.put('/api/chat/history', json=snapshot, headers=account_header()).status_code == 204
    response = client.get('/api/chat/history', headers=account_header())
    assert response.json()['messages'][0]['text'] == label
    assert response.headers['Cache-Control'] == 'no-store'


def test_logout_replay_cannot_extend_recovery_deadline(client, history):
    clock, _ = history
    header = account_header()
    client.put('/api/chat/history', json=SNAPSHOT, headers=header)
    client.post('/api/auth/logout', headers=header)
    clock[0] = 250
    assert client.post('/api/auth/logout', headers=header).status_code == 401
    clock[0] = 301
    assert client.get('/api/chat/history', headers=account_header(1, 2)).json() is None
