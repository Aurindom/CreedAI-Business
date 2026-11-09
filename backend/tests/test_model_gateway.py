import asyncio
import json
import sqlite3
import threading

import httpx
import pytest

from app import model_gateway as gw

CLIENT = 'client-key-0123456789'
PROVIDER = 'sk-or-v1-provider-0123456789'
MODEL = gw.DEFAULT_MODEL


def config(tmp_path, **changes):
    values = dict(upstream='http://provider/v1/chat/completions', provider_key=PROVIDER, client_key=CLIENT,
                  state_path=tmp_path / 'gateway.db', max_requests=3, cap_usd=0.05)
    values.update(changes)
    return gw.GatewayConfig(**values)


class Provider:
    def __init__(self, cost=0.001, status=200, stream_lines=None, raise_on=None):
        self.cost, self.status, self.stream_lines, self.raise_on = cost, status, stream_lines, raise_on
        self.seen = []

    def handler(self, request):
        body = json.loads(request.content)
        self.seen.append({'auth': request.headers['authorization'], 'body': body})
        if self.raise_on == 'connect':
            raise httpx.ConnectError('down')
        if self.status != 200:
            return httpx.Response(self.status, json={'error': 'x'})
        usage = {'prompt_tokens': 10, 'completion_tokens': 5}
        if self.cost is not None:
            usage['cost'] = self.cost
        if body.get('stream'):
            lines = self.stream_lines if self.stream_lines is not None else [
                'data: ' + json.dumps({'choices': [{'delta': {'content': 'hi'}}]}),
                'data: ' + json.dumps({'choices': [], 'usage': usage}),
                'data: [DONE]']
            return httpx.Response(200, stream=Lines(lines, self.raise_on == 'midstream'))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'hi'}}], 'usage': usage})


class Lines(httpx.AsyncByteStream):
    def __init__(self, lines, explode):
        self.lines, self.explode = lines, explode

    async def __aiter__(self):
        for line in self.lines:
            yield (line + '\n\n').encode()
        if self.explode:
            raise httpx.ReadError('cut')


def run(app, body, key=CLIENT):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://gw') as client:
            response = await client.post('/v1/chat/completions', json=body,
                                         headers={'Authorization': f'Bearer {key}'})
            return response.status_code, response.text
    return asyncio.run(go())


def ask(**extra):
    return dict({'model': MODEL, 'messages': [{'role': 'user', 'content': 'hello'}]}, **extra)


def make(tmp_path, provider=None, **changes):
    provider = provider or Provider()
    app = gw.build(config(tmp_path, **changes), httpx.MockTransport(provider.handler))
    return app, provider


def status(app):
    return app.state.gateway.ledger.status()


def test_a_clean_call_is_forwarded_with_forced_limits_and_settled(tmp_path):
    app, provider = make(tmp_path)
    code, text = run(app, ask(max_tokens=5000, temperature=1.2, reasoning_effort='high',
                              max_completion_tokens=9000, top_p=0.5))
    assert code == 200 and json.loads(text)['usage']['cost'] == 0.001
    sent = provider.seen[0]
    assert sent['auth'] == f'Bearer {PROVIDER}'
    body = sent['body']
    assert body['max_tokens'] == gw.MAX_OUTPUT_TOKENS and body['temperature'] == 0
    assert not {'reasoning_effort', 'max_completion_tokens', 'top_p'} & set(body)
    assert body['usage'] == {'include': True}
    assert body['provider'] == {'max_price': {'prompt': gw.INPUT_USD_PER_MTOK, 'completion': gw.OUTPUT_USD_PER_MTOK},
                                'allow_fallbacks': False, 'require_parameters': True}
    found = status(app)
    assert found['by_state'] == {'settled': {'count': 1, 'usd': 0.001}} and found['tripped'] is None


def test_streaming_relays_and_settles_from_the_usage_chunk(tmp_path):
    app, provider = make(tmp_path)
    code, text = run(app, ask(stream=True))
    assert code == 200 and 'data: [DONE]' in text and '"cost": 0.001' in text
    assert provider.seen[0]['body']['stream_options'] == {'include_usage': True}
    assert status(app)['by_state'] == {'settled': {'count': 1, 'usd': 0.001}}


def test_a_bad_client_key_never_reaches_the_provider(tmp_path):
    app, provider = make(tmp_path)
    assert run(app, ask(), key='wrong-key-0123456789')[0] == 401
    assert run(app, ask(), key=PROVIDER)[0] == 401
    assert not provider.seen and status(app)['attempts'] == 0


@pytest.mark.parametrize('body, code', [
    (ask(model='openai/gpt-5'), 'model_not_pinned'),
    (ask(n=2), 'unsupported_field'),
    (ask(modalities=['audio']), 'unsupported_field'),
    (ask(messages=[{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'x'}}]}]),
     'unsupported_modality'),
    (ask(tools=[{'type': 'function', 'function': {'name': 'terminal'}}]), 'tool_not_allowed'),
    (ask(messages=[{'role': 'user', 'content': 'owner_hash=abc'}]), 'forbidden_marker'),
    (ask(messages=[{'role': 'user', 'content': 'key sk-or-v1-abcdefabcdef'}]), 'forbidden_marker'),
    (ask(messages=[{'role': 'user', 'content': 'id 123e4567-e89b-12d3-a456-426614174000'}]), 'forbidden_marker'),
    (ask(messages=[]), 'bad_request'),
    ([1, 2], 'bad_request'),
])
def test_refusals_happen_before_admission(tmp_path, body, code):
    app, provider = make(tmp_path)
    status_code, text = run(app, body)
    assert status_code == 400 and json.loads(text)['error']['code'] == code
    found = status(app)
    assert not provider.seen and found['attempts'] == 0 and found['refused'] == 1


def test_a_configured_forbidden_value_is_refused(tmp_path):
    app, provider = make(tmp_path, forbidden=('acct-secret-value',))
    assert json.loads(run(app, ask(messages=[{'role': 'user', 'content': 'acct-secret-value'}]))[1])['error'][
        'code'] == 'forbidden_marker'
    assert not provider.seen


def test_an_oversized_request_is_refused(tmp_path):
    app, provider = make(tmp_path)
    assert run(app, ask(messages=[{'role': 'user', 'content': 'x' * gw.MAX_REQUEST_BYTES}]))[0] == 413
    assert not provider.seen and status(app)['attempts'] == 0


def test_the_request_cap_counts_every_outbound_attempt(tmp_path):
    app, provider = make(tmp_path, max_requests=2)
    assert [run(app, ask())[0] for _ in range(3)] == [200, 200, 403]
    assert len(provider.seen) == 2
    assert json.loads(run(app, ask())[1])['error']['code'] == 'request_cap'


def test_the_budget_counts_settled_and_reserved_spend(tmp_path):
    one = gw.reservation(len(json.dumps(gw._pinned(ask()))))
    app, provider = make(tmp_path, max_requests=10, cap_usd=one * 1.5, provider=Provider(cost=one * 0.9))
    assert run(app, ask())[0] == 200
    code, text = run(app, ask())
    assert code == 402 and json.loads(text)['error']['code'] == 'budget_exhausted'
    assert len(provider.seen) == 1


def test_parallel_admission_never_exceeds_the_cap(tmp_path):
    ledger = gw.Ledger(tmp_path / 'race.db')
    results, barrier = [], threading.Barrier(12)

    def worker():
        barrier.wait()
        results.append(ledger.admit(0.01, 5, 1.0)[0])
    threads = [threading.Thread(target=worker) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len([r for r in results if r is not None]) == 5
    assert ledger.status()['attempts'] == 5


@pytest.mark.parametrize('provider, reason', [
    (Provider(cost=None), 'usage_missing'),
    (Provider(cost=-1), 'usage_missing'),
    (Provider(cost=10.0), 'usage_over_bound'),
    (Provider(status=500), 'upstream_status'),
    (Provider(status=429), 'upstream_status'),
    (Provider(raise_on='connect'), 'transport_ConnectError'),
])
def test_unverified_usage_holds_the_reservation_and_trips(tmp_path, provider, reason):
    app, _ = make(tmp_path, provider=provider, max_requests=5, cap_usd=100)
    assert run(app, ask())[0] in (200, 502)
    found = status(app)
    assert found['tripped'] == reason and found['by_state']['held']['count'] == 1
    assert found['by_state']['held']['usd'] >= gw.reservation(1)
    code, text = run(app, ask())
    assert code == 403 and json.loads(text)['error']['code'] == 'usage_unverified'
    assert len(provider.seen) == 1


@pytest.mark.parametrize('lines, reason', [
    (['data: ' + json.dumps({'choices': [{'delta': {'content': 'hi'}}]})], 'stream_truncated'),
    (['data: ' + json.dumps({'choices': [{'delta': {}}]}), 'data: [DONE]'], 'usage_missing'),
])
def test_a_stream_without_usage_or_end_is_held(tmp_path, lines, reason):
    app, provider = make(tmp_path, provider=Provider(stream_lines=lines))
    run(app, ask(stream=True))
    assert status(app)['tripped'] == reason
    assert run(app, ask(stream=True))[0] == 403 and len(provider.seen) == 1


def test_a_stream_cut_by_the_provider_is_held(tmp_path):
    app, _ = make(tmp_path, provider=Provider(raise_on='midstream', stream_lines=[
        'data: ' + json.dumps({'choices': [{'delta': {'content': 'hi'}}]})]))
    run(app, ask(stream=True))
    assert status(app)['tripped'] == 'stream_ReadError'


def test_a_client_disconnect_keeps_reading_to_learn_the_cost(tmp_path):
    app, provider = make(tmp_path)
    payload = json.dumps(ask(stream=True)).encode()
    sent = []

    async def go():
        messages = [{'type': 'http.request', 'body': payload, 'more_body': False}]

        async def receive():
            if messages:
                return messages.pop()
            return {'type': 'http.disconnect'}

        async def send(message):
            if message['type'] == 'http.response.body' and sent:
                raise OSError('client gone')
            sent.append(message)
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST',
                 'scheme': 'http', 'path': '/v1/chat/completions', 'raw_path': b'/v1/chat/completions',
                 'query_string': b'', 'root_path': '', 'server': ('gw', 80), 'client': ('c', 1),
                 'headers': [(b'authorization', f'Bearer {CLIENT}'.encode()),
                             (b'content-type', b'application/json')]}
        await app(scope, receive, send)
    asyncio.run(go())
    assert status(app)['by_state'] == {'settled': {'count': 1, 'usd': 0.001}}
    log = [json.loads(line) for line in (tmp_path / 'gateway.jsonl').read_text().splitlines()]
    assert log[-1]['result'] == 'ok' and log[-1]['client_gone'] is True


def test_selection_schema_is_bounded_and_bound_to_the_actual_package(tmp_path):
    app,provider=make(tmp_path)
    package={'claims':[{'id':'bookkeeping:decision'}],'followups':{}}
    system='penny_hermes_selection_v1\nrouting_excerpts: ["I need bookkeeping"]\ninitial_evidence_package: '+json.dumps(package)
    assert run(app,ask(messages=[{'role':'system','content':system},{'role':'user','content':'I need bookkeeping'}]))[0]==200
    schema=provider.seen[0]['body']['response_format']['json_schema']['schema']['properties']
    assert schema['claim_ids']['maxItems']==10
    assert schema['claim_ids']['items']['enum']==['bookkeeping:decision']
    assert schema['followup_id']=={'type':'null'}
    assert provider.seen[0]['body']['max_tokens']==gw.MAX_OUTPUT_TOKENS


def test_an_orphaned_reservation_is_held_on_restart(tmp_path):
    ledger = gw.Ledger(tmp_path / 'gateway.db')
    number, _ = ledger.admit(0.02, 3, 1.0)
    assert number == 1
    app, provider = make(tmp_path)
    found = status(app)
    assert found['tripped'] == 'orphaned' and found['by_state'] == {'held': {'count': 1, 'usd': 0.02}}
    assert run(app, ask())[0] == 403 and not provider.seen


def test_settle_happens_once(tmp_path):
    ledger = gw.Ledger(tmp_path / 'gateway.db')
    number, _ = ledger.admit(0.02, 3, 1.0)
    assert ledger.settle(number, 0.001) and not ledger.settle(number, 0.0)
    ledger.hold(number, 'late')
    assert ledger.status()['by_state'] == {'settled': {'count': 1, 'usd': 0.001}}


def test_the_log_never_holds_prompts_or_keys(tmp_path):
    app, _ = make(tmp_path)
    run(app, ask(messages=[{'role': 'user', 'content': 'my secret plumbing question'}]))
    text = (tmp_path / 'gateway.jsonl').read_text()
    assert 'plumbing' not in text and PROVIDER not in text and CLIENT not in text


def test_state_survives_a_restart(tmp_path):
    app, _ = make(tmp_path, max_requests=1)
    assert run(app, ask())[0] == 200
    again, provider = make(tmp_path, max_requests=1)
    assert run(again, ask())[0] == 403 and not provider.seen
    rows = sqlite3.connect(tmp_path / 'gateway.db').execute('SELECT state FROM attempt').fetchall()
    assert rows == [('settled',)]


@pytest.mark.parametrize('env, bad', [
    ({}, 'UPSTREAM'),
    ({'GATEWAY_UPSTREAM': 'http://p/v1/chat/completions', 'GATEWAY_PROVIDER_KEY': 'short'}, 'KEY'),
    ({'GATEWAY_UPSTREAM': 'http://p/v1/chat/completions', 'GATEWAY_PROVIDER_KEY': 'p' * 20,
      'GATEWAY_CLIENT_KEY': 'p' * 20}, 'KEY'),
    ({'GATEWAY_UPSTREAM': 'http://p/v1/chat/completions', 'GATEWAY_PROVIDER_KEY': 'p' * 20,
      'GATEWAY_CLIENT_KEY': 'c' * 20}, 'MAX_REQUESTS'),
])
def test_config_fails_fast(monkeypatch, env, bad):
    for key in ('GATEWAY_UPSTREAM', 'GATEWAY_PROVIDER_KEY', 'GATEWAY_CLIENT_KEY', 'GATEWAY_MAX_REQUESTS',
                'GATEWAY_CAP_USD', 'GATEWAY_STATE_PATH'):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(gw.ConfigError, match=bad):
        gw.GatewayConfig.from_env()
