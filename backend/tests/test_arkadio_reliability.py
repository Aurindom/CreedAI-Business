import pytest

from app import chat, db, public_mcp
from app.penny_conversation import app_help_reply, business_intake
from test_chat_hermes import hermes, frames, texts, error_code, db_path, rows


@pytest.mark.parametrize('message', [
    'what businesses can you help me with?', 'Which types of businesses do you help?',
    'what can you do?', 'how does this work?',
])
def test_app_help_does_not_start_a_model_or_require_provider_readiness(client, monkeypatch, message):
    async def forbidden(*args, **kwargs):
        raise AssertionError('app help must not call an AI dependency')
    monkeypatch.setattr(chat.readiness, 'check', forbidden)
    monkeypatch.setattr(chat, 'call_model', forbidden)
    events=frames(client.post('/api/chat', json={'conversation_id':'help','message':message,
        'history':[{'role':'user','text':'hello'},{'role':'assistant','text':'Hello!'}]}))
    assert texts(events) and all(e['validation']=='validated' for e in texts(events))
    assert all(e['response_mode']=='app_help' for e in texts(events))
    assert not error_code(events)
    assert events[-1]=={'type':'done'}


@pytest.mark.parametrize('message', ['what businesses can you help me with bookkeeping?',
    'hello, find bookkeeping tools', 'what can Jobber do?', 'clinical symptoms and treatment'])
def test_app_help_does_not_capture_a_product_request_or_medical_question(catalog, message):
    assert app_help_reply(catalog,message) is None


def test_clinical_issues_is_business_intake_not_an_unbounded_model_request():
    from pathlib import Path
    catalog=db.load_catalog_file(Path(__file__).parents[1]/'data/catalog.json')
    assert business_intake(catalog,'clinical issues')=='medical'
    assert business_intake(catalog,'clinical symptoms and treatment') is None


@pytest.mark.parametrize('execute', [True,False])
def test_catalog_mode_requires_actual_executor_receipt(client, hermes, monkeypatch, execute):
    monkeypatch.setenv('CHAT_CATALOG_FAST_PATH','true')
    monkeypatch.setenv('PUBLIC_MCP_URL','http://actions:8000/mcp')
    monkeypatch.setenv('PUBLIC_MCP_TOKEN','test-public-mcp-token')
    async def rpc(http,config,number,method,params):
        assert method=='tools/call'
        if execute:
            public_mcp.lookup(db_path(),params['arguments']['tool_id'],params['arguments']['operation'])
        return {'isError':False}
    monkeypatch.setattr(chat.readiness,'_rpc',rpc)
    response=client.post('/api/chat',json={'conversation_id':'catalog','message':'I need help with bookkeeping',
        'profile':{'trade':'hvac'}})
    assert response.status_code==200,response.text
    events=frames(response)
    if execute:
        assert texts(events) and all(e['response_mode']=='catalog' for e in texts(events))
        assert any(e['type']=='recommendation' for e in events)
        assert all(row[2]=='succeeded' for row in rows())
        assert not error_code(events)
    else:
        assert not texts(events)
        assert error_code(events)=='tool_unavailable'
    assert events[-1]=={'type':'done'}
