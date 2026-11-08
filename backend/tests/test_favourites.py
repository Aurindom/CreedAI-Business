"""Account-owned favourites survive sessions, cache loss and database reopening."""
from pathlib import Path

from app import auth, chat_history, db
from conftest import account_header
from test_chat_history import history


def test_favourites_save_is_idempotent_and_owner_is_server_verified(client):
    alice, bob = account_header(1, 1), account_header(2, 2)
    first = client.put('/api/favourites/jobber', headers=alice)
    assert first.status_code == 200
    assert first.json() == client.put('/api/favourites/jobber', headers=alice).json()
    assert len(client.get('/api/favourites', headers=alice).json()) == 1
    assert client.get('/api/favourites?user_id=1', headers=bob).json() == []
    client.put('/api/favourites/jobber', headers=bob)
    assert client.delete('/api/favourites/jobber', headers=alice).status_code == 204
    assert client.delete('/api/favourites/jobber', headers=alice).status_code == 204
    assert client.get('/api/favourites', headers=alice).json() == []
    assert len(client.get('/api/favourites', headers=bob).json()) == 1


def test_favourites_survive_logout_new_login_and_thirty_day_cache_expiry(client, history):
    clock, _ = history
    old, fresh = account_header(1, 1), account_header(1, 2)
    client.put('/api/favourites/jobber', headers=old)
    assert client.post('/api/auth/logout', headers=old).status_code == 200
    assert client.get('/api/favourites', headers=old).status_code == 401
    assert client.put('/api/favourites/podium', headers=old).status_code == 401
    clock[0] = 31 * 86400
    assert client.get('/api/favourites', headers=fresh).json()[0]['tool_id'] == 'jobber'


def test_favourites_require_valid_identity_and_never_cache_private_responses(client):
    for headers in [{}, {'Authorization': 'Bearer forged'}]:
        for method, url in [('get', '/api/favourites'), ('put', '/api/favourites/jobber'), ('delete', '/api/favourites/jobber')]:
            response = getattr(client, method)(url, headers=headers)
            assert response.status_code == 401
            assert response.headers['cache-control'] == 'no-store'
    response = client.get('/api/favourites', headers=account_header())
    assert response.headers['vary'] == 'Authorization'


def test_invalid_or_rejected_tools_are_not_saved_and_removed_catalog_entries_can_be_unfavourited(client):
    headers = account_header()
    assert client.put('/api/favourites/nonexistent', headers=headers).status_code == 404
    client.put('/api/favourites/jobber', headers=headers)
    catalog = client.app.state.catalog
    client.app.state.catalog = catalog.model_copy(update={'tools': [tool for tool in catalog.tools if tool.id != 'jobber']})
    entry = client.get('/api/favourites', headers=headers).json()[0]
    assert entry['available'] is False
    assert entry['tool_name'] == 'Jobber'
    assert client.put('/api/favourites/jobber', headers=headers).status_code == 404
    assert client.delete('/api/favourites/jobber', headers=headers).status_code == 204


def test_favourites_are_durable_and_do_not_depend_on_redis(client, monkeypatch):
    def unavailable():
        raise RuntimeError('Redis must not be needed')
    monkeypatch.setattr(chat_history, '_cache', unavailable)
    client.put('/api/favourites/jobber', headers=account_header())
    path = client.app.state.conn.execute('PRAGMA database_list').fetchone()[2]
    reopened = db.connect(Path(path))
    try:
        assert reopened.execute('SELECT tool_id FROM favourite_tool').fetchone()[0] == 'jobber'
    finally:
        reopened.close()
    assert client.get('/api/favourites', headers=account_header()).json()[0]['tool_id'] == 'jobber'
