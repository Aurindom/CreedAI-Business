import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from app import access, adoption, auth
from app.schemas import Selection
from conftest import account_header


def test_account_identity_and_workspace_are_stable_across_sessions(client, monkeypatch):
    monkeypatch.delenv('REDIS_URL', raising=False)
    first = client.get('/api/auth/me', headers=account_header(1, 1)).json()
    again = client.get('/api/auth/me', headers=account_header(1, 2)).json()
    other = client.get('/api/auth/me', headers=account_header(2, 3)).json()
    assert first == again
    assert first['user_id'] == str(UUID(int=1))
    assert other['business_id'] != first['business_id']
    assert client.get('/api/auth/me').json()['auth_mode'] == 'guest'


def test_invalid_token_is_not_silently_guest(client):
    assert client.get('/api/auth/me', headers={'Authorization': 'Bearer forged'}).status_code == 401


def test_private_identity_and_plan_responses_are_not_cached(client):
    for path in ('/api/auth/me', '/api/plans'):
        response = client.get(path, headers=account_header())
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.headers['Vary'] == 'Authorization'


def test_account_logout_denies_old_session_but_preserves_plans_for_fresh_login(client):
    first = account_header(1, 1)
    body = {'profile': {'trade': 'hvac'}, 'problem_ids': ['missed_calls'], 'tool_ids': ['jobber'], 'request_id': 'account-confirm-01'}
    saved = client.post('/api/plans', json=body, headers=first)
    assert saved.status_code == 201
    assert client.post('/api/auth/logout', headers=first).status_code == 200
    assert client.get('/api/plans', headers=first).status_code == 401
    assert client.get('/api/plans', headers=account_header(1, 2)).json()[0]['id'] == saved.json()['id']
    assert client.get('/api/plans', headers=account_header(2, 3)).json() == []


def test_legacy_plans_require_explicit_token_proof_and_claim_once(client):
    conn = client.app.state.conn
    now = datetime.now(timezone.utc)
    token, _ = access.create_session(conn, now)
    old_owner = access.owner_for(conn, token, now)
    selection = Selection(profile={'trade': 'hvac'}, problem_ids=['missed_calls'], tool_ids=['jobber'])
    old, _ = adoption.save_plan(conn, client.app.state.catalog, old_owner, 'old-confirm', selection, now)
    alice = account_header(1, 1)
    assert client.get('/api/plans', headers=alice).json() == []
    assert client.post('/api/plans/claim-legacy', json={'legacy_token': 'invalid-' * 4}, headers=alice).status_code == 401
    result = client.post('/api/plans/claim-legacy', json={'legacy_token': token}, headers=alice)
    assert result.json() == {'imported': 1}
    assert client.get('/api/plans', headers=alice).json()[0]['id'] == old.id
    assert client.post('/api/plans/claim-legacy', json={'legacy_token': token}, headers=account_header(2, 2)).status_code == 401
    assert client.get('/api/plans', headers={'Authorization': 'Bearer ' + token}).status_code == 401


def test_guest_cannot_create_new_private_plan_capability(client):
    assert client.post('/api/sessions').status_code == 410
    assert client.get('/api/plans').status_code == 401


def test_account_ownership_anchor_cannot_be_claimed_as_a_legacy_token(client):
    # Even an anchor created by an older deterministic scheme is not a bearer
    # credential. Knowing a victim's public user ID must never transfer plans.
    alice = account_header(1, 1)
    client.get('/api/auth/me', headers=alice)
    guessed_token = 'supabase-account:' + str(UUID(int=1))
    conn = client.app.state.conn
    anchor = access.token_hash(guessed_token)
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute('INSERT INTO owner_session(token_hash,created_at,expires_at) VALUES(?,?,?)', (anchor, now, '9999-12-31T00:00:00+00:00'))
        conn.execute('UPDATE account_owner SET owner_hash=? WHERE user_id=?', (anchor, str(UUID(int=1))))
    response = client.post('/api/plans/claim-legacy', headers=account_header(2, 2), json={'legacy_token': guessed_token})
    assert response.status_code == 401


def token_for(subject, **extra):
    claims = {'sub': subject, 'session_id': str(UUID(int=3)), 'iss': 'https://fixture.supabase.co/auth/v1',
              'aud': 'authenticated', 'exp': 9999999999, **extra}
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return 'fixture.' + encoded + '.not-a-signature'


@pytest.mark.parametrize('status,change,expected', [
    (401, {}, 401), (403, {}, 401), (500, {}, 503),
    (200, {'sub': str(UUID(int=2))}, 401),
    (200, {'exp': 0}, 401), (200, {'iss': 'https://wrong.example/auth/v1'}, 401),
    (200, {'session_id': 'not-a-session'}, 401), (200, {'aud': 'service_role'}, 401),
])
def test_supabase_verification_and_claim_binding_fail_closed(monkeypatch, status, change, expected):
    import asyncio
    monkeypatch.setenv('SUPABASE_URL', 'https://fixture.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'fake-publishable')
    subject = str(UUID(int=1))
    token = token_for(subject, **change)
    class Provider:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, headers):
            assert headers['Authorization'] == 'Bearer ' + token
            return SimpleNamespace(status_code=status, json=lambda: {'id': subject})
    monkeypatch.setattr(auth.httpx, 'AsyncClient', lambda **kwargs: Provider())
    with pytest.raises(Exception) as error:
        asyncio.run(auth.remote_principal(token))
    assert error.value.status_code == expected


def test_anonymous_supabase_user_is_not_a_private_account(monkeypatch):
    import asyncio
    monkeypatch.setenv('SUPABASE_URL', 'https://fixture.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'fake-publishable')
    subject = str(UUID(int=1))
    class Provider:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {'id': subject, 'is_anonymous': True})
    monkeypatch.setattr(auth.httpx, 'AsyncClient', lambda **kwargs: Provider())
    assert not asyncio.run(auth.remote_principal(token_for(subject))).authenticated
