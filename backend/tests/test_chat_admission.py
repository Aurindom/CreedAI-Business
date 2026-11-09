import json
import pytest
from app import chat
from conftest import account_header
from test_chat_hermes import hermes, FakeHermes, answer, frames


def send(client, headers=None, message='Could software reduce administrative overhead?'):
    response = client.post('/api/chat', headers=headers or {}, json={'conversation_id': 'admission', 'message': message})
    assert response.status_code == 200, response.text
    return frames(response)


def limited(events):
    return any(event.get('code') == 'daily_ai_limit' for event in events)


def test_accounts_on_same_network_have_independent_ai_allowances(client, hermes, monkeypatch):
    monkeypatch.setenv('CHAT_DAILY_MESSAGES', '1')
    hermes(FakeHermes(lambda package: answer(package, tools=())))
    a, b = account_header(1, 1), account_header(2, 2)
    assert not limited(send(client, a))
    assert limited(send(client, a))
    assert not limited(send(client, b))
    assert limited(send(client, b))
    # Relogging cannot evade the same account's persistent AI allowance.
    assert limited(send(client, account_header(1, 3)))


def test_free_replies_and_safety_checks_work_after_guest_ai_allowance_exhausted(client, hermes, monkeypatch):
    monkeypatch.setenv('CHAT_DAILY_MESSAGES', '1')
    monkeypatch.setenv('CHAT_CATALOG_FAST_PATH', 'true')
    hermes(FakeHermes(lambda package: answer(package, tools=())))
    assert not limited(send(client))
    blocked = send(client)
    refusal = next(event for event in blocked if event.get('code') == 'daily_ai_limit')
    assert refusal['retryable'] is False and refusal['retry_after_seconds'] > 0
    for message in ('hi', 'what can you do?', '2+2', 'I own a kite repair studio', 'remember my business?'):
        assert client.post('/api/chat/validate', json={'conversation_id': 'admission', 'message': message}).status_code == 200
        assert not limited(send(client, message=message))
    # Free turns did not extend or reset the AI allowance.
    assert limited(send(client))


def test_persistent_daily_allowance_survives_in_memory_limiter_replacement(client, hermes, monkeypatch):
    monkeypatch.setenv('CHAT_DAILY_MESSAGES', '1')
    hermes(FakeHermes(lambda package: answer(package, tools=())))
    assert not limited(send(client, account_header()))
    monkeypatch.setattr(chat, 'limiter', chat.DailyLimiter())
    assert limited(send(client, account_header()))


def test_model_quota_refusal_does_not_reserve_or_send_provider_calls(client, hermes, monkeypatch):
    monkeypatch.setenv('CHAT_DAILY_MESSAGES', '0')
    fake = hermes(FakeHermes(lambda package: answer(package, tools=())))
    before = chat.ledger().total()
    assert limited(send(client))
    assert fake.requests == []
    assert chat.ledger().total() == before


def test_http_refusals_log_fixed_status_without_owner_content(client, monkeypatch, caplog):
    monkeypatch.setenv('CHAT_REQUESTS_PER_MINUTE', '1')
    body = {'conversation_id': 'admission', 'message': 'hi'}
    client.post('/api/chat/validate', json=body)
    with caplog.at_level('WARNING', logger='app.chat'):
        assert client.post('/api/chat/validate', json=body).status_code == 429
    records = [record for record in caplog.records if record.getMessage() == 'chat_request_refused']
    assert records and records[-1].http_status == 429
    assert records[-1].error_code == 'rate_limited'
