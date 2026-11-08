"""Operator-only recovery: retain an entire ambiguous reservation before resuming.

This does not verify the provider's actual bill or mark a held attempt settled.
No request row or dollar charge is reset. Never run automatically from an API.
"""
import argparse
from pathlib import Path
import sqlite3
import time


def acknowledge(path, attempt, expected_reason):
    if Path(path).name != 'discovery-spend.db':
        raise ValueError('Only the discovery ledger is supported')
    with sqlite3.connect('file:' + str(path) + '?mode=rw', uri=True, isolation_level=None) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT state, reason, reserved_usd, charged_usd FROM attempt WHERE n=?', (attempt,)).fetchone()
        trip = conn.execute('SELECT tripped FROM gateway WHERE id=1').fetchone()
        # One known failed attempt, a matching breaker, no in-flight calls, and
        # a full nonzero charge retained. Unknown billing still counts in full.
        held = conn.execute("SELECT count(*) FROM attempt WHERE state='held'").fetchone()[0]
        active = conn.execute("SELECT count(*) FROM attempt WHERE state='reserved'").fetchone()[0]
        if (not row or row[0] != 'held' or row[1] != expected_reason or not trip
                or trip[0] != expected_reason or held != 1 or active
                or row[2] <= 0 or row[3] is None or row[3] < row[2]):
            raise ValueError('Ledger does not match the reviewed recovery checkpoint')
        conn.execute('CREATE TABLE IF NOT EXISTS hold_acknowledgement (attempt INTEGER PRIMARY KEY, reason TEXT NOT NULL, acknowledged REAL NOT NULL)')
        conn.execute('INSERT INTO hold_acknowledgement VALUES (?,?,?)', (attempt, expected_reason, time.time()))
        conn.execute('UPDATE gateway SET tripped=NULL WHERE id=1')
        conn.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--attempt', type=int, required=True)
    parser.add_argument('--expected-reason', required=True)
    parser.add_argument('--retain-full-reservation', action='store_true', required=True)
    args = parser.parse_args()
    acknowledge(args.database, args.attempt, args.expected_reason)
    print('Recovery acknowledged; held state and full charge retained. Existing caps still apply.')
