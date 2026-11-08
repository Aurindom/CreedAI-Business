"""Real two-account Supabase isolation check against the V2 routes, at zero model cost.

Signs in two existing, confirmed QA users (never signs up, never uses a service-role key),
uses real Redis and a throwaway app database, and replaces Hermes with the test-suite fake.
Writes only check names, booleans and status codes. Nothing identifying is printed.

    python backend/scripts/check_two_accounts.py [--env-file sandbox/two-account/.env]
"""
import argparse
import base64
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
REQUIRED = ('SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_TEST_EMAIL', 'SUPABASE_TEST_PASSWORD',
            'SUPABASE_TEST_EMAIL_2', 'SUPABASE_TEST_PASSWORD_2', 'REDIS_URL')


class Stop(Exception):
    pass


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        name, sep, value = line.partition('=')
        if sep and not name.lstrip().startswith('#'):
            values[name.strip()] = value.strip().strip('"').strip("'")
    missing = [name for name in REQUIRED if not values.get(name)]
    if missing:
        raise Stop('missing ' + ', '.join(missing))
    if values['SUPABASE_TEST_EMAIL'].lower() == values['SUPABASE_TEST_EMAIL_2'].lower():
        raise Stop('the two test emails must be different users')
    if is_service_key(values['SUPABASE_PUBLISHABLE_KEY']):
        raise Stop('SUPABASE_PUBLISHABLE_KEY is a secret/service-role key; use the publishable key')
    return values


def is_service_key(key: str) -> bool:
    if key.startswith('sb_secret_'):
        return True
    try:
        return claims(key).get('role') == 'service_role'
    except Exception:
        return False


def claims(token: str) -> dict:
    part = token.split('.')[1]
    return json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))


def b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b'=').decode()


def ignored_by_git(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO)
    except ValueError:
        return True
    probe = subprocess.run(['git', '-C', str(REPO), 'check-ignore', '-q', str(path.resolve())], capture_output=True)
    return probe.returncode == 0


def commit() -> str | None:
    probe = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return probe.stdout.strip() or None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', default=str(REPO / 'sandbox/two-account/.env'))
    parser.add_argument('--out', default=str(REPO / 'sandbox/two-account/result.json'))
    args = parser.parse_args()
    env_file, out = Path(args.env_file), Path(args.out)
    if not env_file.is_file():
        print(json.dumps({'stopped': 'env file not found', 'path': str(env_file)}))
        return 2
    if not ignored_by_git(env_file) or not ignored_by_git(out):
        print(json.dumps({'stopped': 'env file and result must be outside the repo or git-ignored (use sandbox/)'}))
        return 2
    evidence: list[dict] = []
    result = {'commit': commit(), 'paid_model_calls': 0, 'model': 'test-suite fake Hermes', 'checks': evidence}
    result['not_covered_here'] = {
        'frontend_account_switch': 'mocked jsdom: frontend/tests/account-history.test.cjs, account-plans.test.cjs',
        'real_token_expiry': 'app clock moved 2h; real Supabase TTL not waited out',
        'real_model': 'Hermes and the model are faked; no OpenRouter call'}
    try:
        values = read_env(env_file)
        run(values, out.parent / ('state-' + time.strftime('%Y%m%d-%H%M%S')), evidence)
        result['complete'] = True
    except Stop as exc:
        result['stopped'] = str(exc)
    except Exception as exc:
        result['stopped'] = type(exc).__name__
    result['passed'] = sum(1 for e in evidence if e['passed'])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'checks'}))
    return 0 if result.get('complete') else 1


def run(values: dict[str, str], state: Path, evidence: list[dict]) -> None:
    state.mkdir(parents=True, exist_ok=True)
    for name in ('OPENROUTER_API_KEY', 'ANTHROPIC_API_KEY', 'MODEL_GATEWAY_KEY', 'DISCOVERY_OPENROUTER_KEY'):
        os.environ.pop(name, None)
    os.environ.update({
        'SUPABASE_URL': values['SUPABASE_URL'], 'SUPABASE_PUBLISHABLE_KEY': values['SUPABASE_PUBLISHABLE_KEY'],
        'REDIS_URL': values['REDIS_URL'], 'APP_DB_PATH': str(state / 'app.db'),
        'CHAT_SPEND_PATH': str(state / 'spend.db'), 'CHAT_SPEND_CAP_USD': '1', 'PRIVATE_PLANS': 'on',
        'CHAT_RUNTIME': 'hermes', 'HERMES_API_URL': 'http://hermes:8642',
        'HERMES_API_KEY': 'hermes-fake-key-0123456789', 'HERMES_TIMEOUT_SECONDS': '15'})
    for noisy in ('httpx', 'httpcore', 'uvicorn'):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    sys.path[:0] = [str(BACKEND), str(BACKEND / 'tests')]

    import httpx
    from fastapi.testclient import TestClient
    from app import auth
    from app.agent import hermes_runtime, readiness
    from app.main import app
    from test_chat_hermes import FakeHermes, answer, frames, texts

    async def ready():
        return readiness.Readiness(True)
    readiness.check = ready
    readiness.check_now = ready

    def record(name, passed, source, **extra):
        evidence.append({'check': name, 'passed': bool(passed), 'evidence': source, **extra})
        print(json.dumps(evidence[-1]), flush=True)
        if not passed:
            raise Stop('failed: ' + name)

    supa = values['SUPABASE_URL'].rstrip('/')
    key = values['SUPABASE_PUBLISHABLE_KEY']
    secrets = [values[n] for n in ('SUPABASE_TEST_EMAIL', 'SUPABASE_TEST_EMAIL_2')]
    opened = []

    with httpx.Client(timeout=20, follow_redirects=False) as provider, TestClient(app) as client:
        def login(index):
            suffix = '' if index == 1 else '_2'
            reply = provider.post(supa + '/auth/v1/token?grant_type=password', headers={'apikey': key}, json={
                'email': values['SUPABASE_TEST_EMAIL' + suffix], 'password': values['SUPABASE_TEST_PASSWORD' + suffix]})
            if reply.status_code != 200:
                body = reply.json() if reply.headers.get('content-type', '').startswith('application/json') else {}
                code = body.get('error_code') or body.get('error') or ''
                raise Stop(f'account {"A" if index == 1 else "B"} sign-in failed: {reply.status_code} {code}'.strip())
            token = reply.json()['access_token']
            secrets.append(token)
            opened.append({'Authorization': 'Bearer ' + token})
            return token, opened[-1]

        def logout(headers):
            ok = client.post('/api/auth/logout', headers=headers)
            provider.post(supa + '/auth/v1/logout?scope=local', headers={'apikey': key, **headers})
            return ok.status_code == 200 and ok.json().get('signed_out') is True

        def chat_with(fake, headers):
            hermes_runtime.client = lambda config: httpx.AsyncClient(
                transport=httpx.MockTransport(fake.handler), timeout=httpx.Timeout(10, read=config.timeout))
            return client.post('/api/chat', headers=headers, json={
                'conversation_id': 'two-acct-chat', 'message': 'Which tool should I use for bookkeeping?',
                'profile': {'trade': 'hvac'}})

        def history(headers, conversation):
            return client.get('/api/chat/history', params={'conversation_id': conversation}, headers=headers).json()

        def snapshot(conversation, text):
            return {'conversationId': conversation, 'messages': [{'id': 'm1', 'kind': 'user', 'text': text}], 'memory': {}}

        def save_plan(headers):
            return client.post('/api/plans', headers=headers, json={
                'profile': {'trade': 'hvac'}, 'problem_ids': ['missed_calls'], 'tool_ids': ['jobber'],
                'request_id': str(uuid4())})

        def matrix():
            token_a, a = login(1)
            me_a = client.get('/api/auth/me', headers=a).json()
            record('a_signs_in_as_verified_account', me_a['auth_mode'] == 'account', 'real_supabase')
            token_b, b = login(2)
            me_b = client.get('/api/auth/me', headers=b).json()
            record('a_and_b_are_distinct_verified_accounts',
                   me_a['auth_mode'] == me_b['auth_mode'] == 'account' and me_a['user_id'] != me_b['user_id'], 'real_supabase')
            secrets.extend([me_a['user_id'], me_b['user_id'], claims(token_a)['session_id'], claims(token_b)['session_id']])

            record('guest_sees_no_private_data', client.get('/api/auth/me').json()['auth_mode'] == 'guest'
                   and client.get('/api/plans').status_code == 401 and client.get('/api/chat/history').status_code == 401,
                   'real_routes')

            head, body, sig = token_a.split('.')
            forged_sub = '.'.join([head, b64({**claims(token_a), 'sub': me_b['user_id']}), sig])
            bad_sig = '.'.join([head, body, sig[:-2] + ('AA' if sig[-2:] != 'AA' else 'BB')])
            record('forged_tokens_rejected', all(client.get('/api/plans', headers={'Authorization': 'Bearer ' + t}).status_code == 401
                                                 for t in ('forged', forged_sub, bad_sig)), 'real_supabase')

            class Later(datetime):
                @classmethod
                def now(cls, tz=None):
                    return datetime.now(tz) + timedelta(hours=2)
            auth.datetime = Later
            try:
                expired = client.get('/api/plans', headers=a).status_code
            finally:
                auth.datetime = datetime
            record('expired_token_rejected_by_app_claim_check', expired == 401, 'real_token_app_clock_moved_2h')

            plan_a, plan_b = save_plan(a), save_plan(b)
            record('a_and_b_save_plans', plan_a.status_code == plan_b.status_code == 201, 'real_supabase',
                   status=[plan_a.status_code, plan_b.status_code])
            plan_a, plan_b = plan_a.json()['id'], plan_b.json()['id']
            shared, only_b = 'two-acct-' + str(uuid4()), 'two-acct-' + str(uuid4())
            saved = [client.put('/api/chat/history', json=snapshot(shared, 'A private text'), headers=a).status_code,
                     client.put('/api/chat/history', json=snapshot(only_b, 'B private text'), headers=b).status_code]
            record('a_and_b_save_history', saved == [204, 204], 'real_supabase_real_redis', status=saved)

            for me, other, mine, theirs, label in ((a, b, plan_a, plan_b, 'a'), (b, a, plan_b, plan_a, 'b')):
                listed = json.dumps(client.get('/api/plans', headers=me).json())
                record(f'{label}_lists_own_plan_not_other', mine in listed and theirs not in listed, 'real_supabase')
                record(f'{label}_cannot_read_other_plan', client.get('/api/plans/' + theirs, headers=me).status_code == 404, 'real_supabase')
                record(f'{label}_cannot_refresh_other_plan',
                       client.post(f'/api/plans/{theirs}/refresh', headers=me).status_code == 404, 'real_supabase')
            record('b_cannot_restore_a_conversation', history(b, shared) is None, 'real_supabase_real_redis')
            record('a_cannot_restore_b_conversation', history(a, only_b) is None, 'real_supabase_real_redis')
            client.put('/api/chat/history', json=snapshot(shared, 'B overwrite attempt'), headers=b)
            record('same_conversation_id_stays_owner_scoped',
                   history(a, shared)['messages'][0]['text'] == 'A private text'
                   and history(b, shared)['messages'][0]['text'] == 'B overwrite attempt', 'real_supabase_real_redis')

            sent = []
            for headers, label in ((a, 'a'), (b, 'b')):
                fake = FakeHermes(answer)
                events = frames(chat_with(fake, headers))
                record(f'{label}_chat_validated_with_fake_model', texts(events) and events[0]['auth_mode'] == 'account',
                       'real_supabase_fake_hermes')
                sent += [json.dumps([r[2] for r in fake.requests]), json.dumps([r[3] for r in fake.requests])]
            record('model_payload_has_no_account_ids_tokens_or_emails',
                   sent and not any(s in text for s in secrets for text in sent), 'real_supabase_fake_hermes')

            record('a_logout', logout(a), 'real_supabase_real_redis')
            record('revoked_token_rejected', [client.get('/api/plans', headers=a).status_code,
                                              client.get('/api/chat/history', headers=a).status_code,
                                              chat_with(FakeHermes(answer), a).status_code] == [401, 401, 401], 'real_supabase')
            record('b_unaffected_by_a_logout', client.get('/api/plans/' + plan_b, headers=b).status_code == 200, 'real_supabase')

            _, a2 = login(1)
            started, holder = threading.Event(), {}
            slow = FakeHermes(answer, delay=1.0, on_wait=started.set)
            worker = threading.Thread(target=lambda: holder.update(r=chat_with(slow, a2)))
            worker.start()
            started.wait(10)
            logout(a2)
            worker.join(30)
            events = frames(holder['r'])
            codes = [e.get('code') for e in events if e.get('code')]
            record('logout_mid_run_blocks_delivery', not texts(events) and codes == ['session_expired']
                   and ('POST', '/v1/runs/run_abc/stop') in slow.paths(), 'real_supabase_fake_hermes', codes=codes)

            _, a3 = login(1)
            restored = history(a3, shared)
            record('a_recovers_own_conversation_within_five_minutes',
                   restored is not None and restored['messages'][0]['text'] == 'A private text', 'real_supabase_real_redis')
            record('plans_persist_and_stay_isolated_after_relogin',
                   client.get('/api/plans/' + plan_a, headers=a3).status_code == 200
                   and client.get('/api/plans/' + plan_a, headers=b).status_code == 404
                   and history(a3, only_b) is None, 'real_supabase')
            record('final_logout', logout(a3) and logout(b), 'real_supabase')

        try:
            matrix()
        except BaseException:
            for headers in opened:
                try:
                    logout(headers)
                except Exception:
                    pass
            raise


if __name__ == '__main__':
    raise SystemExit(main())
