import importlib.util
from pathlib import Path
import sqlite3

import pytest

from app.model_gateway import Ledger

spec = importlib.util.spec_from_file_location('hold_recovery', Path(__file__).parents[1]/'scripts/acknowledge_discovery_hold.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def test_operator_recovery_preserves_unknown_charge_state_and_limits(tmp_path):
    path = tmp_path/'discovery-spend.db'
    ledger = Ledger(path)
    number, _ = ledger.admit(.25, 3, .5)
    ledger.hold(number, 'search_http_500')
    before = ledger.status()
    recovery.acknowledge(path, number, 'search_http_500')
    after = ledger.status()
    assert after['by_state'] == before['by_state']
    assert after['committed_usd'] == .25 and after['tripped'] is None
    assert ledger.admit(.26, 3, .5)[1] == 'budget_exhausted'
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM hold_acknowledgement').fetchone()[0] == 1
    with pytest.raises(ValueError):
        recovery.acknowledge(path, number, 'search_http_500')


@pytest.mark.parametrize('mismatch', ['wrong_reason', 'multiple_held', 'inflight'])
def test_recovery_refuses_an_unreviewed_or_active_ledger(tmp_path, mismatch):
    path = tmp_path/'discovery-spend.db'; ledger = Ledger(path)
    number, _ = ledger.admit(.25, 5, 2)
    ledger.hold(number, 'search_http_500')
    if mismatch != 'wrong_reason':
        with sqlite3.connect(path) as conn:
            conn.execute('UPDATE gateway SET tripped=NULL')
        other, _ = ledger.admit(.25, 5, 2)
        if mismatch == 'multiple_held':
            ledger.hold(other, 'search_http_500')
        else:
            with sqlite3.connect(path) as conn:
                conn.execute("UPDATE gateway SET tripped='search_http_500'")
    with pytest.raises(ValueError):
        recovery.acknowledge(path, number, 'incorrect' if mismatch == 'wrong_reason' else 'search_http_500')
    assert ledger.status()['tripped'] == 'search_http_500'
