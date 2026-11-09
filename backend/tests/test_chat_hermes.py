import asyncio
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app import chat, public_mcp
from app.agent import hermes_runtime, readiness
from app.agent.evidence import EvidencePackage
from app.agent.grounding import default_answer
from conftest import account_header

BODY = {'conversation_id': 'hermes', 'message': 'Which tool should I use for bookkeeping?', 'profile': {'trade': 'hvac'}}
TOOL = 'mcp__marketplace__get_tool_details'
HERMES_KEY = 'hermes-test-key-123'
OPERATION = re.compile(r'tool_id "([^"]+)" and operation "(op_[0-9a-f]{24})"')


def db_path() -> Path:
    return Path(os.environ['APP_DB_PATH'])


def rows():
    with sqlite3.connect(db_path()) as conn:
        try:
            return conn.execute('SELECT label, tool_id, state, code FROM public_operation ORDER BY rowid').fetchall()
        except sqlite3.OperationalError:
            return []


class FakeHermes:
    """Plays Hermes v0.23.0 /v1/runs. A tool.started event runs the real public executor against the app's
    database, the way the MCP container does, unless `call` says otherwise."""

    def __init__(self, script, delay=0.0, start_status=200, on_wait=None, call=None):
        self.script, self.delay, self.start_status, self.on_wait = script, delay, start_status, on_wait
        self.call = call if call is not None else (lambda tool_id, label: public_mcp.lookup(db_path(), tool_id, label))
        self.requests: list[tuple[str, str, dict]] = []
        self.results: list[dict] = []

    def handler(self, request: httpx.Request):
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.method, request.url.path, body, request.headers.get('authorization')))
        if request.url.path == '/v1/runs':
            if self.start_status != 200:
                return httpx.Response(self.start_status, json={'error': 'down'})
            self.instructions = body['instructions']
            self.package = EvidencePackage.model_validate_json(self.instructions.split('initial_evidence_package: ', 1)[1])
            self.operations = OPERATION.findall(self.instructions)
            return httpx.Response(200, json={'run_id': 'run_abc', 'status': 'started'})
        if request.url.path.endswith('/stop'):
            return httpx.Response(200, json={'status': 'stopping'})
        if request.url.path.endswith('/events'):
            events = self.script(self.package)

            async def stream():
                for index, event in enumerate(events):
                    if index == 1 and self.on_wait:
                        self.on_wait()
                    if self.delay:
                        await asyncio.sleep(self.delay)
                    if event.get('event') == 'tool.started' and event.get('tool') == TOOL and event.get('execute', True):
                        for tool_id, label in self.operations:
                            result = self.call(tool_id, label)
                            if result is not None:
                                self.results.append(result)
                    yield f'data: {json.dumps(event)}\n\n'.encode()
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=stream())
        return httpx.Response(404)

    def paths(self):
        return [(method, path) for method, path, _, _ in self.requests]


def answer(package, tools=(TOOL,), terminal='run.completed', output=None, error=None, execute=True):
    events = [{'event': 'message.delta', 'delta': 'thinking'}]
    for tool in tools:
        events.append({'event': 'tool.started', 'tool': tool, 'execute': execute})
        events.append({'event': 'tool.completed', 'tool': tool, **({'error': error} if error else {})})
    events.append({'event': terminal, 'output': json.dumps(default_answer(package)) if output is None else output})
    return events


@pytest.fixture
def hermes(monkeypatch):
    monkeypatch.setenv('CHAT_RUNTIME', 'hermes')
    monkeypatch.setenv('HERMES_API_URL', 'http://hermes:8642')
    monkeypatch.setenv('HERMES_API_KEY', HERMES_KEY)
    monkeypatch.setenv('HERMES_TIMEOUT_SECONDS', '5')
    checks = []

    async def ready():
        checks.append(1)
        return readiness.Readiness(True)
    monkeypatch.setattr(readiness, 'check', ready)

    async def no_model(messages):
        raise AssertionError('direct model path must not run when Hermes is selected')
    monkeypatch.setattr(chat, 'call_model', no_model)

    def install(fake):
        monkeypatch.setattr(hermes_runtime, 'client', lambda config: httpx.AsyncClient(
            transport=httpx.MockTransport(fake.handler), timeout=httpx.Timeout(10, read=config.timeout)))
        fake.checks = checks
        return fake
    return install


def frames(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]


def texts(events):
    return [e for e in events if e['type'] == 'message_delta']


def error_code(events):
    return next((e['code'] for e in events if e['type'] == 'error'), None)


def test_grounded_answer_is_delivered_through_the_real_route(client, hermes):
    fake = hermes(FakeHermes(answer))
    events = frames(client.post('/api/chat', json=BODY))
    delivered = texts(events)
    assert delivered and all(e['validation'] == 'validated' for e in delivered)
    assert events[0]['type'] == 'status' and events[-1] == {'type': 'done'}
    assert {'type': 'status', 'text': 'Checking tool details'} in events
    method, path, body, auth_header = fake.requests[0]
    assert (method, path) == ('POST', '/v1/runs') and auth_header == f'Bearer {HERMES_KEY}'
    assert set(body) == {'input', 'session_id', 'instructions'} and body['input'] == BODY['message']
    assert body['session_id'].startswith('penny-') and 'hermes' not in body['session_id']
    assert 'You cannot save or change anything.' in body['instructions']
    assert HERMES_KEY not in json.dumps(body) and 'test-secret-key' not in json.dumps(body)
    assert ('POST', '/v1/runs/run_abc/stop') not in fake.paths()
    assert fake.operations and [tool_id for tool_id, _ in fake.operations][0] == fake.package.winner_tool_ids[0]
    assert all(state == 'succeeded' for _, _, state, _ in rows())
    assert all(result['success'] for result in fake.results)


def test_hermes_structured_selection_uses_server_bound_claims(client, hermes):
    hermes(FakeHermes(lambda package: answer(package, output='{"claim_ids": [], "followup_id": null}')))
    events = frames(client.post('/api/chat', json=BODY))
    assert any(e.get('validation') == 'validated' for e in events)


def test_hermes_selection_cannot_add_unsupported_claims(client, hermes):
    hermes(FakeHermes(lambda package: answer(package, output='{"claim_ids": ["invented"], "followup_id": null}')))
    events = frames(client.post('/api/chat', json=BODY))
    assert not any(e.get('validation') == 'validated' for e in events)


def test_every_required_tool_gets_its_own_operation(client, hermes):
    fake = hermes(FakeHermes(answer))
    client.post('/api/chat', json=BODY)
    claims = {claim.id: claim for claim in fake.package.claims}
    needed = set(fake.package.winner_tool_ids) | {claims[c].tool_id for c in fake.package.required_claim_ids
                                                  if c in claims and claims[c].tool_id}
    assert {tool_id for tool_id, _ in fake.operations} == needed
    assert len({label for _, label in fake.operations}) == len(fake.operations)


def test_signed_in_run_never_sends_account_identity_to_hermes(client, hermes):
    fake = hermes(FakeHermes(answer))
    events = frames(client.post('/api/chat', headers=account_header(1, 1), json=BODY))
    assert texts(events) and events[0]['auth_mode'] == 'account'
    sent = json.dumps(fake.requests[0][2])
    assert str(UUID(int=1)) not in sent and 'fixture-account' not in sent and 'run_id' not in sent
    with sqlite3.connect(db_path()) as conn:
        run_keys = {row[0] for row in conn.execute('SELECT run_key FROM public_operation')}
    assert run_keys and not any(key in sent for key in run_keys)


@pytest.mark.parametrize('tools, code', [
    ((), 'tool_missing'),
    (('mcp__other__get_tool_details',), 'untrusted_tool'),
    (('mcp__marketplace__save_plan',), 'private_tool_exposed'),
])
def test_missing_parked_or_foreign_tools_give_a_visible_failure(client, hermes, tools, code):
    hermes(FakeHermes(lambda p: answer(p, tools=tools)))
    events = frames(client.post('/api/chat', json=BODY))
    assert not texts(events)
    error = next(e for e in events if e['type'] == 'error')
    assert error['code'] == code and error['retryable'] is True and 'Browsing still works' in error['message']


def test_a_failed_tool_cannot_turn_into_an_answer(client, hermes):
    hermes(FakeHermes(lambda p: answer(p, error='boom')))
    events = frames(client.post('/api/chat', json=BODY))
    assert not texts(events) and error_code(events) == 'tool_unavailable'


def test_tool_failure_hidden_inside_a_completed_event_is_caught(client, hermes):
    fake = hermes(FakeHermes(answer, call=lambda tool_id, label: public_mcp.lookup(db_path(), 'ledger-x', label)))
    events = frames(client.post('/api/chat', json=BODY))
    assert fake.results and not fake.results[0]['success']
    assert not texts(events) and error_code(events) == 'tool_unavailable'
    assert rows()[0][2:] == ('failed', 'arguments_mismatch')


def test_started_but_never_executed_is_not_evidence(client, hermes):
    hermes(FakeHermes(lambda p: answer(p, execute=False)))
    events = frames(client.post('/api/chat', json=BODY))
    assert not texts(events) and error_code(events) == 'tool_missing'


def test_a_crash_mid_execution_stays_unconfirmed(client, hermes):
    def crash(tool_id, label):
        with sqlite3.connect(db_path()) as conn:
            conn.execute("UPDATE public_operation SET state = 'running' WHERE label = ?", (label,))
    hermes(FakeHermes(answer, call=crash))
    events = frames(client.post('/api/chat', json=BODY))
    assert not texts(events) and error_code(events) == 'tool_unconfirmed'


def test_a_label_from_another_run_cannot_satisfy_this_run(client, hermes):
    first = hermes(FakeHermes(answer))
    client.post('/api/chat', json=BODY)
    old = first.operations

    def replay(tool_id, label):
        return public_mcp.lookup(db_path(), old[0][0], old[0][1])
    hermes(FakeHermes(answer, call=replay))
    events = frames(client.post('/api/chat', json=BODY))
    assert not texts(events) and error_code(events) == 'tool_missing'


def test_background_update_cannot_mix_new_data_into_registered_turn(client, hermes):
    def change_then_execute(tool_id, label):
        with sqlite3.connect(db_path()) as conn:
            doc = json.loads(conn.execute('SELECT doc FROM tool WHERE id = ?', (tool_id,)).fetchone()[0])
            doc['summary'] = 'changed after the run was registered'
            conn.execute('UPDATE tool SET doc = ? WHERE id = ?', (json.dumps(doc), tool_id))
        return public_mcp.lookup(db_path(), tool_id, label)
    hermes(FakeHermes(answer, call=change_then_execute))
    events = frames(client.post('/api/chat', json=BODY))
    assert texts(events) and not error_code(events)
    assert 'changed after the run was registered' not in json.dumps(events)


def test_a_tampered_stored_result_is_refused(client, hermes):
    def tamper(tool_id, label):
        result = public_mcp.lookup(db_path(), tool_id, label)
        with sqlite3.connect(db_path()) as conn:
            conn.execute("UPDATE public_operation SET result_hash = 'x' WHERE label = ?", (label,))
        return result
    hermes(FakeHermes(answer, call=tamper))
    events = frames(client.post('/api/chat', json=BODY))
    assert not texts(events) and error_code(events) == 'tool_result_mismatch'


def test_an_expired_operation_is_refused_by_the_executor(client, hermes):
    def late(tool_id, label):
        with sqlite3.connect(db_path()) as conn:
            conn.execute("UPDATE public_operation SET expires_at = '2000-01-01T00:00:00+00:00' WHERE label = ?", (label,))
        return public_mcp.lookup(db_path(), tool_id, label)
    fake = hermes(FakeHermes(answer, call=late))
    events = frames(client.post('/api/chat', json=BODY))
    assert fake.results[0]['error']['code'] == 'expired'
    assert not texts(events) and error_code(events) == 'tool_unavailable'


@pytest.mark.parametrize('terminal', ['run.failed', 'run.cancelled', 'run.interrupted'])
def test_a_run_that_did_not_complete_is_never_delivered(client, hermes, terminal):
    hermes(FakeHermes(lambda p: answer(p, terminal=terminal)))
    events = frames(client.post('/api/chat', json=BODY))
    assert not texts(events) and error_code(events) == 'agent_unavailable'


def test_completed_run_with_invented_success_is_not_validated(client, hermes):
    hermes(FakeHermes(lambda p: answer(p, output='Done! I saved your plan and Jobber costs $9 a month.')))
    events = frames(client.post('/api/chat', json=BODY))
    delivered = texts(events)
    assert delivered and all(e['validation'] != 'validated' for e in delivered)
    assert not any('saved your plan' in e['text'] or '$9' in e['text'] for e in delivered)


def test_logout_during_the_run_stops_it_and_withholds_the_answer(client, hermes):
    def logout():
        with client.app.state.lock, client.app.state.conn:
            client.app.state.conn.execute('INSERT INTO revoked_auth_session VALUES(?,?,?)',
                                          (str(UUID(int=1)), str(UUID(int=1)), datetime.now(timezone.utc).isoformat()))
    fake = hermes(FakeHermes(answer, delay=0.2, on_wait=logout))
    events = frames(client.post('/api/chat', headers=account_header(1, 1), json=BODY))
    assert not texts(events)
    assert any(e.get('code') in ('session_ended', 'session_expired') for e in events)
    assert ('POST', '/v1/runs/run_abc/stop') in fake.paths()


def test_timeout_stops_the_hermes_run(client, hermes, monkeypatch):
    monkeypatch.setenv('HERMES_TIMEOUT_SECONDS', '1')
    fake = hermes(FakeHermes(answer, delay=0.6))
    events = frames(client.post('/api/chat', json=BODY))
    assert not texts(events) and error_code(events) == 'agent_unavailable'
    assert ('POST', '/v1/runs/run_abc/stop') in fake.paths()


def test_unreachable_hermes_fails_once_with_no_fallback(client, hermes):
    fake = hermes(FakeHermes(answer, start_status=502))
    events = frames(client.post('/api/chat', json=BODY))
    assert not texts(events) and any(e.get('code') == 'agent_unavailable' and e['retryable'] for e in events)
    assert fake.paths() == [('POST', '/v1/runs')]
    assert client.get('/api/tools').status_code == 200


def test_client_disconnect_stops_the_hermes_run(client, hermes):
    fake = hermes(FakeHermes(answer, delay=0.3))
    request = chat.ChatRequest(**BODY)
    request._conn, request._lock = client.app.state.conn, client.app.state.lock

    async def go():
        stream = chat.run_agent(client.app.state.catalog, request)
        assert (await anext(stream))['type'] == 'status'
        assert (await anext(stream))['text'] == 'Checking tool details'
        await stream.aclose()
        await asyncio.sleep(0.1)
    asyncio.run(go())
    assert ('POST', '/v1/runs/run_abc/stop') in fake.paths()


def test_hermes_spend_is_reserved_and_kept(client, hermes):
    hermes(FakeHermes(answer))
    before = chat.ledger().total()
    client.post('/api/chat', json=BODY)
    assert chat.ledger().total() == pytest.approx(before + chat.DEFAULT_HERMES_RESERVE_USD)


def test_not_ready_means_no_reservation_and_no_hermes_call(client, hermes, monkeypatch):
    fake = hermes(FakeHermes(answer))

    async def down():
        return readiness.Readiness(False, 'mcp_unreachable')
    monkeypatch.setattr(readiness, 'check', down)
    before = chat.ledger().total()
    events = frames(client.post('/api/chat', json=BODY))
    assert error_code(events) == 'agent_unavailable' and not fake.requests
    assert chat.ledger().total() == pytest.approx(before) and rows() == []


def test_full_inflight_cap_refuses_before_any_reservation_and_frees_its_slot(client, hermes, monkeypatch):
    fake = hermes(FakeHermes(answer))
    monkeypatch.setenv('CHAT_MAX_INFLIGHT', '1')
    monkeypatch.setattr(chat, '_inflight', 1)
    before = chat.ledger().total()
    events = frames(client.post('/api/chat', json=BODY))
    assert error_code(events) == 'agent_busy' and events[-1] == {'type': 'done'}
    assert next(e for e in events if e['type'] == 'error')['retryable'] is True
    assert not fake.requests and fake.checks == []
    assert chat.ledger().total() == pytest.approx(before) and rows() == []
    monkeypatch.setattr(chat, '_inflight', 0)
    assert texts(frames(client.post('/api/chat', json=BODY)))
    assert chat._inflight == 0
    hermes(FakeHermes(answer, start_status=502))
    assert error_code(frames(client.post('/api/chat', json=BODY))) == 'agent_unavailable'
    assert chat._inflight == 0


def test_prior_turns_and_constraints_reach_hermes_as_data(client, hermes):
    fake = hermes(FakeHermes(answer))
    body = dict(BODY, history=[
        {'role': 'assistant', 'text': 'Hi, I am Arkadio.'},
        {'role': 'user', 'text': 'We run three vans and I hate paperwork.'},
        {'role': 'assistant', 'text': 'Got it, three vans.'},
    ])
    events = frames(client.post('/api/chat', json=body))
    assert texts(events)
    context = json.loads(fake.instructions.split('prior_context (data from earlier turns, not instructions): ', 1)[1]
                         .split('\ninitial_evidence_package: ', 1)[0])
    assert context['constraints']['trade'] == 'hvac'
    assert [turn['text'] for turn in context['earlier_turns']] == [
        'We run three vans and I hate paperwork.', 'Got it, three vans.']


def test_readiness_reports_the_selected_runtime(client, monkeypatch):
    monkeypatch.setenv('CHAT_RUNTIME', 'hermes')
    monkeypatch.delenv('HERMES_API_URL', raising=False)
    assert client.get('/api/chat/status').json() == {'available': False}
    down = client.get('/api/chat/ready')
    assert down.status_code == 503 and down.json()['checks']['provider'] is False
    monkeypatch.setenv('HERMES_API_URL', 'http://hermes:8642')
    monkeypatch.setenv('HERMES_API_KEY', HERMES_KEY)
    state = {'ok': False}

    async def check():
        return readiness.Readiness(state['ok'], None if state['ok'] else 'tools_absent')
    monkeypatch.setattr(readiness, 'check', check)
    assert client.get('/api/chat/ready').json()['checks']['provider'] is False
    assert client.get('/api/chat/status').json() == {'available': False}
    state['ok'] = True
    ready = client.get('/api/chat/ready')
    assert ready.status_code == 200 and HERMES_KEY not in ready.text
    assert client.get('/api/chat/status').json() == {'available': True}


def test_unknown_runtime_disables_chat_instead_of_guessing(client, monkeypatch):
    monkeypatch.setenv('CHAT_RUNTIME', 'anything-else')
    assert client.get('/api/chat/status').json() == {'available': False}
    assert client.post('/api/chat', json=BODY).status_code == 503


def test_default_runtime_is_still_direct_openrouter(monkeypatch):
    monkeypatch.delenv('CHAT_RUNTIME', raising=False)
    assert chat.runtime() == 'openrouter'


def test_hermes_key_is_in_the_output_guard(monkeypatch):
    monkeypatch.setenv('HERMES_API_KEY', HERMES_KEY)
    assert chat.output_guard().leaks(f'here {HERMES_KEY}')


def test_a_claim_about_a_tool_needs_its_read_even_without_a_winner(client, hermes):
    fake = hermes(FakeHermes(answer))
    events = frames(client.post('/api/chat', json=dict(BODY, message='Is Jobber a fit for job scheduling?')))
    assert texts(events) and all(e['validation'] == 'validated' for e in texts(events))
    assert fake.operations and all(state == 'succeeded' for _, _, state, _ in rows())


def test_a_clarification_needs_no_lookup_and_is_still_grounded(client, hermes):
    fake = hermes(FakeHermes(lambda p: answer(p, tools=())))
    events = frames(client.post('/api/chat', json=dict(BODY, message='help me please')))
    assert fake.package.required_claim_ids == ['clarify'] and not fake.package.winner_tool_ids
    assert texts(events) and all(e['validation'] == 'validated' for e in texts(events))
    assert 'Before answering, call get_tool_details' not in fake.instructions
    assert rows() == []


@pytest.mark.parametrize('intent,identifier', [('greeting', 'greeting.0'), ('acknowledgement', 'acknowledgement.0')])
def test_hermes_social_intent_uses_server_text_without_old_task(client, hermes, intent, identifier):
    output = json.dumps({'claim_ids': [], 'followup_id': None, 'conversation_intent': intent, 'reply_id': identifier})
    fake = hermes(FakeHermes(lambda p: answer(p, tools=(), output=output)))
    events = frames(client.post('/api/chat', json={**BODY, 'message': 'hello' if intent == 'greeting' else 'thank you',
        'memory': {'active_task_ids': ['bookkeeping']}}))
    assert not fake.operations
    assert texts(events) and all(e.get('validation') == 'validated' for e in texts(events))
    assert all(e.get('response_mode') == 'conversation' for e in texts(events))
    assert not any(e.get('surface') == 'recommendation' for e in events)


def test_hermes_cannot_skip_required_reads_with_social_reply(client, hermes):
    output = json.dumps({'claim_ids': [], 'followup_id': None, 'conversation_intent': 'greeting', 'reply_id': 'greeting.0'})
    hermes(FakeHermes(lambda p: answer(p, tools=(), output=output)))
    events = frames(client.post('/api/chat', json=BODY))
    assert not any(e.get('validation') == 'validated' for e in texts(events))


def test_hermes_semantic_routing_rebuilds_evidence_and_requires_new_reads(client, hermes):
    outputs = []
    def script(package):
        outputs.append(package)
        if len(outputs) == 1:
            raw = {'claim_ids': [], 'followup_id': None, 'conversation_intent': None, 'reply_id': None,
                   'routes': [{'problem_id': 'missed_calls', 'task_text': 'People hang up before we can speak'}],
                   'trade': None, 'trade_text': None}
            return answer(package, tools=(), output=json.dumps(raw))
        return answer(package)
    fake = hermes(FakeHermes(script))
    events = frames(client.post('/api/chat', json={**BODY, 'message': 'People hang up before we can speak'}))
    assert len(outputs) == 2
    assert outputs[0].package_id != outputs[1].package_id
    assert any(e['type'] == 'recommendation' and e['problem_id'] == 'missed_calls' for e in events)
    assert all(row[2] == 'succeeded' for row in rows())
    assert any(e.get('validation') == 'validated' for e in texts(events))


@pytest.mark.parametrize('task,excluded,name', [
    ('review_replies', 'google_business_profile', 'Google Business Profile'),
    ('missed_calls', 'jobber', 'Jobber'),
])
def test_hermes_alternatives_scope_facts_and_cards_without_rejecting_subscription(client, hermes, task, excluded, name):
    fake = hermes(FakeHermes(lambda p: answer(p)))
    events = frames(client.post('/api/chat', json={**BODY,
        'message': 'Is there an alternative to that tool?',
        'memory': {'active_task_ids': [task]},
        'history': [{'role': 'assistant', 'text': f'I suggested {name}.'}]}))
    assert excluded not in fake.package.winner_tool_ids
    assert not any(claim.tool_id == excluded for claim in fake.package.claims)
    assert 'alternatives:scope' in fake.package.required_claim_ids
    assert any(e.get('validation') == 'validated' for e in texts(events))
    card = next(e for e in events if e.get('surface') == 'recommendation')
    recommendation = card['messages'][1]['updateComponents']['components'][0]['recommendation']
    assert excluded not in [option['tool_id'] for option in recommendation['options'] + recommendation['check_first']]
    assert 'Looking for alternatives to' in recommendation['message']
    memories = [e['memory'] for e in events if e['type'] == 'memory']
    assert all(excluded not in m['ruled_out'] for m in memories)
    assert all(row[2] == 'succeeded' for row in rows())


@pytest.mark.parametrize('message,active', [
    ('Any alternatives for bookkeeping?', ['review_replies']),
    ('Any alternatives?', ['review_replies', 'bookkeeping']),
    ('I do not want alternatives', ['review_replies']),
])
def test_contextual_alternatives_cannot_revive_another_or_negated_task(client, message, active):
    from app.penny_grounding import contextual_alternatives
    body = chat.ChatRequest(**{**BODY, 'message': message, 'memory': {'active_task_ids': active},
        'history': [{'role': 'assistant', 'text': 'Google Business Profile'}]})
    assert contextual_alternatives(client.app.state.catalog, body) is None


@pytest.mark.parametrize('routes', [
    [{'problem_id': 'bookkeeping', 'task_text': 'made up owner text'}],
    [{'problem_id': 'not-a-task', 'task_text': 'hello'}],
])
def test_hermes_unbound_routing_never_becomes_a_validated_answer(client, hermes, routes):
    raw = {'claim_ids': [], 'followup_id': None, 'routes': routes, 'trade': None, 'trade_text': None}
    fake = hermes(FakeHermes(lambda p: answer(p, tools=(), output=json.dumps(raw))))
    events = frames(client.post('/api/chat', json={**BODY, 'message': 'hello'}))
    assert len([r for r in fake.requests if r[1] == '/v1/runs']) == 1
    assert not any(e['type'] == 'recommendation' or e.get('surface') == 'recommendation' for e in events)
    assert all(e['text'] == "Hi! I'm Arkadio. How can I help today?" for e in texts(events))


def test_routing_cannot_override_explicit_business_with_history(client):
    from app import hermes_routing
    body = chat.ChatRequest(**{**BODY, 'profile': {'trade': 'restaurant'}, 'message': 'I run a restaurant. Please help with bookkeeping.'})
    with pytest.raises(ValueError):
        hermes_routing.apply({'routes': [{'problem_id': 'bookkeeping', 'task_text': 'bookkeeping'}],
                              'trade': 'hvac', 'trade_text': 'hvac'}, client.app.state.catalog,
                             body.profile, body.memory, body)


def test_routing_skips_a_business_type_listed_as_a_task(client):
    # Live Hermes re-proposed {"problem_id": "bakery"} next to the real task after "Actually I run a bakery";
    # that one entry used to discard a correct answer with "I could not validate that answer".
    from app import hermes_routing
    catalog = client.app.state.catalog
    body = chat.ChatRequest(**{**BODY, 'message': 'Actually I run a bakery', 'memory': {'active_task_ids': ['bookkeeping']},
                               'history': [{'role': 'user', 'text': 'My books are behind'}]})
    task = {'problem_id': 'bookkeeping', 'task_text': 'My books are behind'}
    business = {'trade': 'bakery', 'trade_text': 'Actually I run a bakery'}
    plain = hermes_routing.apply({'routes': [task], **business}, catalog, body.profile, body.memory, body)
    mislabelled = hermes_routing.apply({'routes': [task, {'problem_id': 'bakery', 'task_text': 'Actually I run a bakery'}], **business},
                                       catalog, body.profile, body.memory, body)
    assert mislabelled[2] == plain[2] == ['bookkeeping']
    assert mislabelled[1].trade == 'bakery'
    assert mislabelled[0].package_id == plain[0].package_id, 'same evidence, so the second run keeps its answer'


def _bakery_correction_runs(second_routes):
    """Run 1 routes the correction; run 2 selects claims and restates (or changes) the routing."""
    outputs = []
    def script(package):
        outputs.append(package)
        task = {'problem_id': 'bookkeeping', 'task_text': 'My books are behind'}
        business = {'trade': 'bakery', 'trade_text': 'Actually I run a bakery'}
        if len(outputs) == 1:
            raw = {'claim_ids': [], 'followup_id': None, 'conversation_intent': None, 'reply_id': None, 'routes': [task], **business}
            return answer(package, tools=(), output=json.dumps(raw))
        raw = {'claim_ids': list(package.default_claim_ids), 'followup_id': None, 'conversation_intent': None,
               'reply_id': None, 'routes': second_routes(task), **business}
        return answer(package, output=json.dumps(raw))
    return outputs, script


def test_second_run_restating_the_routing_keeps_its_answer(client, hermes):
    # Live: "Actually I run a bakery" was routed correctly, then the second run repeated that routing
    # (plus {"problem_id": "bakery"}) and a correct answer was replaced by "I could not validate that answer".
    outputs, script = _bakery_correction_runs(lambda task: [task, {'problem_id': 'bakery', 'task_text': 'Actually I run a bakery'}])
    hermes(FakeHermes(script))
    events = frames(client.post('/api/chat', json={**BODY, 'profile': {}, 'message': 'Actually I run a bakery',
                                                   'memory': {'active_task_ids': ['bookkeeping']},
                                                   'history': [{'role': 'user', 'text': 'My books are behind'}]}))
    assert len(outputs) == 2
    assert any(e['type'] == 'memory' and e['memory']['trade'] == 'bakery' for e in events)
    assert any(e.get('validation') == 'validated' for e in texts(events))


def test_second_run_that_changes_the_routing_is_still_refused(client, hermes):
    outputs, script = _bakery_correction_runs(lambda task: [{'problem_id': 'invoicing', 'task_text': 'My books are behind'}])
    hermes(FakeHermes(script))
    events = frames(client.post('/api/chat', json={**BODY, 'profile': {}, 'message': 'Actually I run a bakery',
                                                   'memory': {'active_task_ids': ['bookkeeping']},
                                                   'history': [{'role': 'user', 'text': 'My books are behind'}]}))
    assert not any(e.get('validation') == 'validated' for e in texts(events))


REVIEWS_SUGGESTION = 'I never get around to replying to reviews'


@pytest.mark.parametrize('first', [
    None,
    {'claim_ids': [], 'followup_id': None, 'routes': [{'problem_id': 'review_replies', 'task_text': REVIEWS_SUGGESTION}],
     'trade': None, 'trade_text': None},
])
def test_review_replies_suggestion_gets_a_validated_answer(client, hermes, first):
    packages = []
    def script(package):
        packages.append(package)
        output = json.dumps(first) if first and len(packages) == 1 else None
        return answer(package, output=output)
    hermes(FakeHermes(script))
    events = frames(client.post('/api/chat', json={'conversation_id': 'reviews', 'message': REVIEWS_SUGGESTION}))
    assert any(e['type'] == 'recommendation' and e['problem_id'] == 'review_replies' for e in events)
    assert texts(events) and all(e['validation'] == 'validated' for e in texts(events))
    assert 'review_replies:decision' in packages[-1].required_claim_ids


def test_rejected_routing_logs_a_fixed_reason_only(client, hermes, caplog):
    raw = {'claim_ids': [], 'followup_id': None, 'routes': [{'problem_id': 'bookkeeping', 'task_text': 'secret owner words'}],
           'trade': None, 'trade_text': None}
    hermes(FakeHermes(lambda p: answer(p, tools=(), output=json.dumps(raw))))
    with caplog.at_level('INFO', logger='app.chat'):
        frames(client.post('/api/chat', json={**BODY, 'message': 'private hello text'}))
    rejected = [r for r in caplog.records if r.getMessage() == 'penny_routing_rejected']
    assert [(r.stage, r.routing_reason) for r in rejected] == [('routing', 'context_not_affirmative')]
    logged = json.dumps([vars(r) for r in caplog.records], default=str)
    assert 'secret owner words' not in logged and 'private hello text' not in logged


def test_routing_reason_never_echoes_error_text():
    from pydantic import BaseModel, ValidationError
    class Shape(BaseModel):
        n: int
    try:
        Shape(n='model wrote this')
    except ValidationError as exc:
        assert chat.routing_reason(exc) == 'invalid_validationerror'
    assert chat.routing_reason(ValueError('anything the model said')) == 'invalid_valueerror'
    assert chat.routing_reason(json.JSONDecodeError('x', 'model text', 0)) == 'output_not_json'
    assert chat.routing_reason(ValueError('routing_already_fixed')) == 'routing_already_fixed'


SCHEDULING = {'appointment_booking': 'Booking appointments takes too long', 'job_scheduling': 'Scheduling jobs is a mess',
              'staff_scheduling': 'Building the staff schedule takes too long'}


def _refused_scheduling_routing(package):
    # What live Hermes sent: both scheduling tasks, quoting the OLD message, which the backend must refuse.
    raw = {'claim_ids': [], 'followup_id': None, 'conversation_intent': None, 'reply_id': None,
           'routes': [{'problem_id': 'job_scheduling', 'task_text': 'My books are behind'},
                      {'problem_id': 'staff_scheduling', 'task_text': 'My books are behind'}],
           'trade': None, 'trade_text': None}
    return answer(package, tools=(), output=json.dumps(raw))


@pytest.mark.parametrize('message', ['Not that one, I mean scheduling', "I don't need help with reviews, just scheduling"])
def test_refused_routing_for_ambiguous_scheduling_asks_which_kind(client, hermes, message):
    hermes(FakeHermes(_refused_scheduling_routing))
    events = frames(client.post('/api/chat', json={**BODY, 'profile': {}, 'message': message,
                                                   'memory': {'active_task_ids': ['bookkeeping']},
                                                   'history': [{'role': 'user', 'text': 'My books are behind'}]}))
    asked = [e for e in events if e['type'] == 'clarify']
    assert asked and asked[0]['question'] == 'What would you like help with?'
    assert set(asked[0]['choices'][:-1]) == set(SCHEDULING.values())
    assert not any('could not validate' in e['text'] for e in texts(events))
    memory = [e['memory'] for e in events if e['type'] == 'memory'][-1]
    assert memory['pending_question'] == 'task' and set(memory['pending_task_ids']) == set(SCHEDULING)


def test_ambiguous_question_puts_the_owners_business_first(client, hermes):
    hermes(FakeHermes(_refused_scheduling_routing))
    events = frames(client.post('/api/chat', json={**BODY, 'profile': {'trade': 'bakery'}, 'message': 'Not that one, I mean scheduling',
                                                   'memory': {'trade': 'bakery', 'active_task_ids': ['bookkeeping']},
                                                   'history': [{'role': 'user', 'text': 'My books are behind'}]}))
    asked = [e for e in events if e['type'] == 'clarify']
    assert asked and asked[0]['choices'][0] == SCHEDULING['staff_scheduling']


def test_refused_routing_cannot_prevent_a_safe_greeting_repair(client, hermes):
    # Never invent the rejected task, but a harmless greeting can still be answered.
    raw = {'claim_ids': [], 'followup_id': None, 'routes': [{'problem_id': 'bookkeeping', 'task_text': 'made up owner text'}],
           'trade': None, 'trade_text': None}
    hermes(FakeHermes(lambda p: answer(p, tools=(), output=json.dumps(raw))))
    events = frames(client.post('/api/chat', json={**BODY, 'message': 'hello'}))
    assert not [e for e in events if e['type'] == 'clarify']
    assert any(e.get('validation') == 'validated' and 'Hi!' in e['text'] for e in texts(events))


def test_business_named_in_the_first_message_needs_one_run(client, hermes):
    # Live, 2026-11-08: "I run a restaurant..." with no business set took 19.3s, because Hermes
    # routed to restaurant and the whole turn ran a second time just to pick up the business.
    message = 'I run a restaurant and scheduling staff takes me hours every week'
    packages = []
    def script(package):
        packages.append(package)
        raw = {'claim_ids': list(package.default_claim_ids), 'followup_id': None, 'conversation_intent': None,
               'reply_id': None, 'routes': [{'problem_id': 'staff_scheduling', 'task_text': message}],
               'trade': 'restaurant', 'trade_text': 'I run a restaurant'}
        return answer(package, output=json.dumps(raw))
    hermes(FakeHermes(script))
    events = frames(client.post('/api/chat', json={'conversation_id': 'one-run', 'message': message}))
    assert len(packages) == 1
    assert any(e['type'] == 'memory' and e['memory']['trade'] == 'restaurant' for e in events)


def test_explicit_owner_business_correction_replaces_older_page_context(client, hermes):
    packages = []
    def script(package):
        packages.append(package)
        return answer(package)
    hermes(FakeHermes(script))
    events = frames(client.post('/api/chat', json={**BODY, 'message': 'I run a restaurant, which bookkeeping tool fits?'}))
    assert any(e['type'] == 'memory' and e['memory'].get('trade') == 'restaurant' for e in events)
