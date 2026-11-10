"""Budget authority, retry bounds, and adversarial memory regressions."""
import asyncio
import json

import httpx
import pytest

from app import chat, model_gateway as gw
from app.agent import readiness
from app.conversation_state import business_description
from test_chat_hermes import BODY, FakeHermes, answer, frames, hermes, texts
from test_model_gateway import CLIENT, ask, config, run


@pytest.mark.parametrize('question', [
    'do you think that my business is ready',
    'can you check whether my business is profitable?',
    'remind me what my business is please',
    'If my business is a bakery, what would you suggest?',
])
def test_questions_do_not_overwrite_business(question):
    assert business_description(question) is None


def test_gateway_authority_preserves_old_ledger_without_blocking_model(client, hermes, monkeypatch):
    monkeypatch.setenv('CHAT_BUDGET_AUTHORITY', 'gateway')
    monkeypatch.setenv('CHAT_SPEND_CAP_USD', '0')
    book = chat.ledger()
    book.settle(0, 4.02)
    fake = hermes(FakeHermes(answer))
    assert chat.chat_available()
    assert texts(frames(client.post('/api/chat', json=BODY)))
    assert book.total() == pytest.approx(4.02)
    assert 'Gateway turn: ' in json.dumps(fake.requests)


def test_gateway_authority_does_not_enable_direct_provider_bypass(monkeypatch):
    monkeypatch.setenv('CHAT_BUDGET_AUTHORITY', 'gateway')
    monkeypatch.setenv('CHAT_RUNTIME', 'openrouter')
    assert not chat.runtime_configured()


def test_budget_refusal_happens_before_daily_admission(client, hermes, monkeypatch):
    hermes(FakeHermes(answer))
    monkeypatch.setattr(chat, 'chat_available', lambda: True)
    monkeypatch.setenv('CHAT_SPEND_CAP_USD', '0')
    monkeypatch.setattr(chat, '_admit_model_turn', lambda _: pytest.fail('daily allowance consumed'))
    events = frames(client.post('/api/chat', json=BODY))
    assert any(e.get('code') == 'ai_budget_reached' and not e['retryable'] for e in events)


def tagged(turn='a' * 32, stream=False):
    return ask(messages=[{'role': 'system', 'content': 'Instructions\nGateway turn: ' + turn + '\n'},
                         {'role': 'user', 'content': 'synthetic test'}], stream=stream, max_tokens=9000)


@pytest.mark.parametrize('stream', [False, True])
def test_only_one_larger_truncation_recovery_and_usage_retained(tmp_path, stream):
    seen = []
    def provider(request):
        body = json.loads(request.content)
        seen.append(body)
        assert 'Gateway turn:' not in request.content.decode()
        usage = {'completion_tokens': body['max_tokens'], 'cost': .009}
        choice = {'finish_reason': 'length', 'message': {'content': '{"incomplete":'}, 'delta': {'content': '{'}}
        if stream:
            text = 'data: ' + json.dumps({'choices': [choice], 'usage': usage}) + '\n\ndata: [DONE]\n\n'
            return httpx.Response(200, content=text, headers={'Content-Type': 'text/event-stream'})
        return httpx.Response(200, json={'choices': [choice], 'usage': usage})
    cfg = config(tmp_path, max_requests=0, cap_usd=0, enforce_lifetime_limits=False)
    app = gw.build(cfg, httpx.MockTransport(provider))
    assert run(app, tagged(stream=stream))[0] == 200
    assert run(app, tagged(stream=stream))[0] == 200
    for _ in range(4):
        code, text = run(app, tagged(stream=stream))
        assert code == 403 and 'truncation_retry_exhausted' in text
    assert [b['max_tokens'] for b in seen] == [800, 1600]
    assert app.state.gateway.ledger.status()['committed_usd'] == pytest.approx(.018)
    # A different owner's run is not disabled; restart preserves the retry bound.
    app = gw.build(cfg, httpx.MockTransport(provider))
    assert run(app, tagged(stream=stream))[0] == 403
    assert run(app, tagged('b' * 32, stream=stream))[0] == 200


def test_successful_recovery_can_continue_to_tool_result(tmp_path):
    seen = []
    def provider(request):
        body = json.loads(request.content)
        seen.append(body['max_tokens'])
        return httpx.Response(200, json={'choices': [{'finish_reason': 'length' if len(seen) == 1 else 'stop',
                                                     'message': {'content': '{}'}}],
                                         'usage': {'completion_tokens': 900 if len(seen) > 1 else 800, 'cost': .005}})
    app = gw.build(config(tmp_path, max_requests=10, cap_usd=1), httpx.MockTransport(provider))
    for _ in range(3):
        assert run(app, tagged())[0] == 200
    assert seen == [800, 1600, 1600]
    assert app.state.gateway.ledger.status()['tripped'] is None


def test_turn_call_bound_survives_disabled_lifetime_limits(tmp_path):
    from test_model_gateway import Provider
    provider = Provider()
    app = gw.build(config(tmp_path, max_requests=0, cap_usd=0, enforce_lifetime_limits=False),
                   httpx.MockTransport(provider.handler))
    for _ in range(gw.MAX_CALLS_PER_TURN):
        assert run(app, tagged())[0] == 200
    assert run(app, tagged())[0] == 403
    assert len(provider.seen) == gw.MAX_CALLS_PER_TURN


def test_unknown_usage_still_blocks_uncapped_gateway(tmp_path):
    from test_model_gateway import Provider
    provider = Provider(cost=None)
    app = gw.build(config(tmp_path, max_requests=0, cap_usd=0, enforce_lifetime_limits=False),
                   httpx.MockTransport(provider.handler))
    run(app, tagged())
    assert run(app, tagged('b' * 32))[0] == 403
    assert len(provider.seen) == 1


def test_readiness_understands_explicit_disabled_lifetime_limits(monkeypatch):
    monkeypatch.setenv('MODEL_GATEWAY_URL', 'http://gateway:9999')
    monkeypatch.setenv('MODEL_GATEWAY_KEY', CLIENT)
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        'attempts': 700, 'max_requests': 500, 'committed_usd': 5, 'cap_usd': 4,
        'enforce_lifetime_limits': False, 'tripped': None}))
    real = httpx.AsyncClient
    monkeypatch.setattr(readiness.httpx, 'AsyncClient', lambda **kw: real(transport=transport, **kw))
    assert asyncio.run(readiness.gateway_ready()).ok
