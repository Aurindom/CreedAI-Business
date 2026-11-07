"""Operator tools for discovered records that left the active catalog.

Seeding moves a discovered tool into the quarantine table when the current catalog can no longer hold
it, or archives it when a reviewed tool now covers the same product. Nothing here is reachable over
HTTP. Run it as `python scripts/quarantine.py list|inspect|revalidate|restore`.
"""

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from . import db
from .domains import identity
from .schemas import Catalog, Tool

BACKEND_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Outcome:
    ok: bool
    reason: str | None = None
    details: str = ""
    canonical_id: str | None = None


def _row(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM quarantine WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise KeyError(f"no quarantined record with key {key}")
    return row


def list_records(conn: sqlite3.Connection, state: str | None = None) -> list[dict[str, str | None]]:
    conn.row_factory = sqlite3.Row
    sql = "SELECT key, tool_id, state, reason, canonical_id, quarantined_at FROM quarantine"
    rows = conn.execute(sql + (" WHERE state = ?" if state else "") + " ORDER BY quarantined_at, key", (state,) if state else ()).fetchall()
    return [dict(r) for r in rows]


def inspect(conn: sqlite3.Connection, key: str, with_raw: bool = False) -> dict:
    row = dict(_row(conn, key))
    if not with_raw:
        row.pop("raw")
    row["audit"] = [
        dict(r) for r in conn.execute("SELECT action, outcome, reason, at FROM quarantine_audit WHERE key = ? ORDER BY id", (key,)).fetchall()
    ]
    return row


def _check(conn: sqlite3.Connection, catalog: Catalog, row: sqlite3.Row) -> Outcome:
    if row["state"] == db.RESTORED:
        return Outcome(False, "already_restored", "this record is already back in the catalog")
    verdict = db.judge(row["raw"], catalog, {t.id for t in catalog.tools}, {identity(t): t.id for t in catalog.tools})
    if verdict:
        return Outcome(False, *verdict[:2], canonical_id=verdict[2])
    found = Tool.model_validate_json(row["raw"])
    live = db.read_catalog(conn)
    if db.judge(row["raw"], live, set(), {}):
        return Outcome(False, "catalog_conflict", "the running database still holds the older catalog, so restart the app to re-seed it first")
    for active in live.tools:
        if active.id == found.id:
            return Outcome(False, "active_id_conflict", "a tool with this id is already active", active.id)
        if identity(active) == identity(found):
            return Outcome(False, "active_identity_conflict", "the same product is already active", active.id)
    return Outcome(True)


def _audit(conn: sqlite3.Connection, key: str, action: str, outcome: str, reason: str | None) -> None:
    conn.execute(
        "INSERT INTO quarantine_audit (key, action, outcome, reason, at) VALUES (?, ?, ?, ?, ?)",
        (key, action, outcome, reason, db.now_text()),
    )


def revalidate(conn: sqlite3.Connection, catalog: Catalog, key: str) -> Outcome:
    """Checks a record against today's catalog rules without changing it, and logs the check."""
    row = _row(conn, key)
    outcome = _check(conn, catalog, row)
    with conn:
        _audit(conn, key, "revalidate", "valid" if outcome.ok else "invalid", outcome.reason)
    return outcome


def restore(conn: sqlite3.Connection, catalog: Catalog, key: str) -> Outcome:
    """Puts a valid record back as a pending discovered tool. Curated facts and active rows are never touched.

    A record that still fails stays in quarantine unchanged and the reason comes back. The original text is
    kept after a restore, marked restored, with an audit entry.
    """
    row = _row(conn, key)
    outcome = _check(conn, catalog, row)
    with conn:
        if not outcome.ok:
            _audit(conn, key, "restore", "refused", outcome.reason)
            return outcome
        found = Tool.model_validate_json(row["raw"]).model_copy(update={"status": "pending_review", "origin": db.DISCOVERED})
        db.put_discovered(conn, found)
        conn.execute("UPDATE quarantine SET state = ?, restored_at = ? WHERE key = ?", (db.RESTORED, db.now_text(), key))
        _audit(conn, key, "restore", "restored", None)
    return outcome


def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, default))


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="quarantine", description="Look after discovered records that left the active catalog.")
    parser.add_argument("--db", type=Path, default=_env_path("APP_DB_PATH", BACKEND_DIR / "data" / "app.db"))
    parser.add_argument("--catalog", type=Path, default=_env_path("CATALOG_PATH", BACKEND_DIR / "data" / "catalog.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--state", choices=[db.QUARANTINED, db.ARCHIVED, db.RESTORED])
    show = sub.add_parser("inspect")
    show.add_argument("key")
    show.add_argument("--raw", action="store_true")
    for name in ("revalidate", "restore"):
        sub.add_parser(name).add_argument("key")
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"no database at {args.db}", file=out)
        return 2
    conn = db.connect(args.db)
    try:
        if args.command == "list":
            rows = list_records(conn, args.state)
            for r in rows:
                link = f" -> {r['canonical_id']}" if r["canonical_id"] else ""
                print(f"{r['key']}  {r['state']}  {r['reason']}{link}", file=out)
            print(f"{len(rows)} record(s)", file=out)
            return 0
        if args.command == "inspect":
            print(json.dumps(inspect(conn, args.key, args.raw), indent=2), file=out)
            return 0
        catalog = db.load_catalog_file(args.catalog)
        outcome = (revalidate if args.command == "revalidate" else restore)(conn, catalog, args.key)
        if outcome.ok:
            print("restored as pending_review" if args.command == "restore" else "valid against the current catalog", file=out)
            return 0
        link = f" (see {outcome.canonical_id})" if outcome.canonical_id else ""
        print(f"not restorable: {outcome.reason}: {outcome.details}{link}" if args.command == "restore" else f"invalid: {outcome.reason}: {outcome.details}{link}", file=out)
        return 1
    except KeyError as exc:
        print(exc.args[0], file=out)
        return 2
    finally:
        conn.close()
