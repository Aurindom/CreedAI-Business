import json
from pathlib import Path

import pytest

from app.schemas import Catalog, Trade
from test_chat import client

CASES = json.loads((Path(__file__).parent / 'fixtures/business_types.json').read_text())
CATALOG = Catalog.model_validate_json((Path(__file__).parents[1] / 'data/catalog.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['text'])
def test_business_aliases_and_conservative_typo_handling(case):
    assert CATALOG.resolve_trade(case['text']) == case['expected']


def test_every_existing_business_name_and_id_still_resolves():
    for trade in CATALOG.trades:
        assert CATALOG.resolve_trade(trade.id) == trade.id
        assert CATALOG.resolve_trade(trade.name) == trade.id


def test_ambiguous_alias_is_not_guessed():
    ambiguous = CATALOG.model_copy(update={'trades': [Trade(id='a', name='First', aliases=['Mechanic shop']), Trade(id='b', name='Second', aliases=['Mechanic shop'])]})
    assert ambiguous.resolve_trade('mechanic shop') is None
    assert ambiguous.resolve_trade('mechainc shop') is None


def test_api_filters_and_recommendations_use_the_same_business_category(client):
    trades = client.get('/api/trades').json()
    assert 'Mechanic shop' in next(trade for trade in trades if trade['id'] == 'auto')['aliases']
    for endpoint in ('problems', 'tools'):
        assert client.get(f'/api/{endpoint}', params={'trade': 'mechainc shop'}).json() == client.get(f'/api/{endpoint}', params={'trade': 'auto'}).json()
    def result(trade):
        response = client.post('/api/recommend', json={'profile': {'trade': trade}, 'problem_id': 'missed_calls'})
        assert response.status_code == 200
        return response.json()
    assert result('mechanic shop') == result('auto')
