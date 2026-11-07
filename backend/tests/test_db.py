import sqlite3

import pytest

from app import db
from conftest import cap, tool


def ids(conn):
    return {t.id for t in db.read_catalog(conn).tools}


def found(tool_id="found", price=20, **extra):
    return tool(tool_id, price, [cap("phone")], **{"status": "pending_review", **extra})


def test_discovered_tool_survives_a_restart_and_catalog_rows_refresh(tmp_path, catalog):
    path = tmp_path / "app.db"
    conn = db.connect(path)
    db.seed(conn, catalog)
    db.add_discovered_tool(conn, found())
    conn.close()

    dropped = catalog.tools.pop()
    conn = db.connect(path)
    db.seed(conn, catalog)
    assert ids(conn) == {t.id for t in catalog.tools} | {"found"}
    assert dropped.id not in ids(conn)


def test_repeat_discovery_updates_one_row(tmp_path, catalog):
    conn = db.connect(tmp_path / "app.db")
    db.seed(conn, catalog)
    db.add_discovered_tool(conn, found(price=20))
    db.add_discovered_tool(conn, found(price=35))
    stored = [t for t in db.read_catalog(conn).tools if t.id == "found"]
    assert len(stored) == 1 and stored[0].entry_monthly_usd.value == 35


def test_catalog_entry_takes_over_a_discovered_tool_with_the_same_id(tmp_path, catalog):
    conn = db.connect(tmp_path / "app.db")
    db.seed(conn, catalog)
    db.add_discovered_tool(conn, found())
    catalog.tools.append(tool("found", 25, [cap("phone")]))
    db.seed(conn, catalog)
    assert conn.execute("SELECT origin, status FROM tool WHERE id = 'found'").fetchall() == [(db.CATALOG, "verified")]


def test_discovery_cannot_overwrite_the_catalog_or_arrive_verified(tmp_path, catalog):
    conn = db.connect(tmp_path / "app.db")
    db.seed(conn, catalog)
    with pytest.raises(ValueError, match="already in the reviewed catalog"):
        db.add_discovered_tool(conn, found(catalog.tools[0].id))
    with pytest.raises(ValueError, match="verified"):
        db.add_discovered_tool(conn, found(status="verified"))


def test_old_database_without_origin_is_upgraded_as_catalog_rows(tmp_path, catalog):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE tool (id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, doc TEXT NOT NULL)")
    old.execute("INSERT INTO tool VALUES ('stale', 'Stale', 'verified', '{}')")
    old.commit()
    old.close()
    conn = db.connect(path)
    db.seed(conn, catalog)
    assert ids(conn) == {t.id for t in catalog.tools}
