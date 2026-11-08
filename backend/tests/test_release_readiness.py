import asyncio
import copy
import json

import httpx
import pytest

from app.agent import completion, readiness, tool_execution


@pytest.mark.parametrize('changes,code', [
    ({}, None),
    ({'attempts': 5}, 'gateway_exhausted'),
    ({'committed_usd': 5}, 'gateway_exhausted'),
    ({'tripped': 'usage_missing'}, 'gateway_usage_unverified'),
    ({'attempts': '0'}, 'gateway_status_invalid'),
    ({'cap_usd': -1}, 'gateway_status_invalid'),
])
def test_live_gateway_state_is_checked_even_when_mcp_health_cached(monkeypatch, changes, code):
    monkeypatch.setenv('MODEL_GATEWAY_URL', 'http://gateway:9999')
    monkeypatch.setenv('MODEL_GATEWAY_KEY', 'fixture-gateway-client-key')
    data = {'attempts': 0, 'max_requests': 5, 'committed_usd': 0, 'cap_usd': 5, 'tripped': None}
    data.update(changes)
    seen = []
    def handler(request):
        seen.append(request.url.path)
        assert request.headers['authorization'] == 'Bearer fixture-gateway-client-key'
        return httpx.Response(200, json=data)
    real = httpx.AsyncClient
    monkeypatch.setattr(readiness.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(readiness, '_healthy_until', float('inf'))
    assert asyncio.run(readiness.check()).code == code
    assert seen == ['/gateway/status']


@pytest.mark.parametrize('mutation', ['wrong_type', 'optional_operation', 'not_object', 'null_property', 'bad_required'])
def test_matching_field_names_do_not_hide_schema_failures(mutation):
    schema = {'type': 'object', 'properties': {'tool_id': {'type': 'string'}, 'operation': {'type': 'string'}},
              'required': ['tool_id', 'operation']}
    if mutation == 'wrong_type':
        schema['properties']['tool_id']['type'] = 'number'
    elif mutation == 'optional_operation':
        schema['required'] = ['tool_id']
    elif mutation == 'not_object':
        schema['type'] = 'array'
    elif mutation == 'null_property':
        schema['properties']['tool_id'] = None
    else:
        schema['required'] = 7
    assert completion.check_tools(['get_tool_details'], {'get_tool_details': schema}, layer='listed') == 'tool_unavailable'


def test_completed_lookup_must_finish_before_its_execution_deadline(tmp_path, catalog):
    from app import db
    connection = db.connect(tmp_path / 'deadline.db')
    try:
        key, ops = tool_execution.register(connection, None, catalog, ['ledger'], 60)
        assert tool_execution.execute(connection, catalog, ops[0].label, 'ledger')['success']
        with connection:
            connection.execute("UPDATE public_operation SET finished_at='9999-01-01T00:00:00+00:00'")
        assert not tool_execution.verify(connection, None, catalog, key, ops).ok
    finally:
        connection.close()
