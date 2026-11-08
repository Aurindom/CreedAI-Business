import threading

import pytest

from app import live_discovery
from app.discovery import DiscoveryRequest


def test_public_research_is_opt_in_and_no_operator_secret_is_exposed(client, monkeypatch):
    monkeypatch.delenv('DISCOVERY_PUBLIC_ENABLED', raising=False)
    assert client.get('/api/discovery/status').json() == {'available': False}
    assert client.post('/api/research', json={'capability': 'phone_answering'}).status_code == 503


def test_exhausted_discovery_budget_is_unavailable_before_search(client, monkeypatch):
    monkeypatch.setenv('DISCOVERY_PUBLIC_ENABLED', 'true')
    def finder(*args):
        raise AssertionError('Exhausted source must never be called')
    finder.available = lambda: False
    client.app.state.discovery_finder = finder
    assert client.get('/api/discovery/status').json() == {'available': False}
    assert client.post('/api/research', json={'capability': 'phone_answering'}).status_code == 503


def test_public_research_limits_survive_multiple_calls_and_unknown_task_never_searches(client, monkeypatch):
    monkeypatch.setenv('DISCOVERY_PUBLIC_ENABLED', 'true')
    calls = []
    def finder(request, cancel):
        calls.append(request.capability)
        return {'contract_version': '1.1.0', 'run_id': 'bounded', 'status': 'completed',
                'provenance': 'live', 'candidates': [], 'limits': {'pages_fetched': 1, 'elapsed_s': 0.01}}
    client.app.state.discovery_finder = finder
    assert client.get('/api/discovery/status').json() == {'available': True}
    assert client.post('/api/research', json={'capability': 'invented'}).status_code == 422
    assert not calls
    for _ in range(4):
        assert client.post('/api/research', json={'capability': 'phone_answering'}).status_code == 200
    assert client.post('/api/research', json={'capability': 'phone_answering'}).status_code == 429
    assert len(calls) == 4
    assert client.get('/api/tools').status_code == 200


@pytest.mark.parametrize('excerpt,kept', [
    ('Answer calls from your laptop without picking up your phone.', False),
    ('Our AI receptionist answers calls automatically for small businesses.', True),
])
def test_task_verbs_on_hardware_pages_do_not_become_business_software(catalog, tmp_path, monkeypatch, excerpt, kept):
    monkeypatch.delenv('DISCOVERY_SEARCH_PROVIDER', raising=False)
    candidate = {'capabilities': ['phone'], 'evidence': [{'field': 'capability.phone', 'excerpt': excerpt}]}
    monkeypatch.setattr(live_discovery, 'discover_tools', lambda *args: {'candidates': [candidate]})
    finder = live_discovery.make_finder(catalog, tmp_path / 'worker.db')
    try:
        data = finder(DiscoveryRequest(capability='phone'), threading.Event())
        assert ('phone' in data['candidates'][0]['capabilities']) is kept
    finally:
        finder.close()
