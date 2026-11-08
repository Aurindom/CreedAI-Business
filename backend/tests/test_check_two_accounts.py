import base64
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'check_two_accounts', Path(__file__).resolve().parents[1] / 'scripts' / 'check_two_accounts.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

GOOD = {
    'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_abc',
    'SUPABASE_TEST_EMAIL': 'qa-a@example.com', 'SUPABASE_TEST_PASSWORD': 'pw-a',
    'SUPABASE_TEST_EMAIL_2': 'qa-b@example.com', 'SUPABASE_TEST_PASSWORD_2': 'pw-b',
    'REDIS_URL': 'redis://127.0.0.1:16390/0'}


def write(tmp_path, values):
    path = tmp_path / '.env'
    path.write_text('\n'.join(f'{k}={v}' for k, v in values.items()), encoding='utf-8')
    return path


def legacy_key(role):
    body = base64.urlsafe_b64encode(json.dumps({'role': role}).encode()).rstrip(b'=').decode()
    return f'eyJhbGciOiJIUzI1NiJ9.{body}.sig'


def test_reads_a_complete_env_file(tmp_path):
    assert checker.read_env(write(tmp_path, GOOD))['SUPABASE_TEST_EMAIL_2'] == 'qa-b@example.com'


def test_refuses_missing_values(tmp_path):
    with pytest.raises(checker.Stop, match='SUPABASE_TEST_PASSWORD_2'):
        checker.read_env(write(tmp_path, {**GOOD, 'SUPABASE_TEST_PASSWORD_2': ''}))


def test_refuses_the_same_account_twice(tmp_path):
    with pytest.raises(checker.Stop, match='different users'):
        checker.read_env(write(tmp_path, {**GOOD, 'SUPABASE_TEST_EMAIL_2': 'QA-A@example.com'}))


@pytest.mark.parametrize('key', ['sb_secret_abc', legacy_key('service_role')])
def test_refuses_service_role_keys(tmp_path, key):
    with pytest.raises(checker.Stop, match='service-role'):
        checker.read_env(write(tmp_path, {**GOOD, 'SUPABASE_PUBLISHABLE_KEY': key}))


def test_accepts_a_legacy_anon_key(tmp_path):
    assert checker.read_env(write(tmp_path, {**GOOD, 'SUPABASE_PUBLISHABLE_KEY': legacy_key('anon')}))


def test_refuses_an_env_file_git_would_track(tmp_path):
    assert checker.ignored_by_git(tmp_path / '.env')
    assert checker.ignored_by_git(checker.REPO / 'sandbox' / 'two-account' / '.env')
    assert not checker.ignored_by_git(checker.REPO / 'two-account.env')
