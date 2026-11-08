import io
import json

import pytest

from app import db, quarantine
from app.schemas import Catalog
from conftest import tool

FOUND = dict(status="pending_review")


def plant(conn, found):
    db.add_discovered_tool(conn, found)


def removed_trade(catalog):
    return catalog.model_copy(update={
        "trades": [t for t in catalog.trades if t.id != "restaurant"],
        "tools": [t for t in catalog.tools if "restaurant" not in t.trades],
    })


@pytest.fixture
def conn(catalog, tmp_path):
    c = db.connect(tmp_path / "q.db")
    db.seed(c, catalog)
    return c


def keys(conn, state=None):
    return [r["key"] for r in quarantine.list_records(conn, state)]


def test_an_incompatible_record_keeps_its_original_text_and_stays_out_of_reads(conn, catalog):
    diner = tool("diner-bot", 20, [], trades=("restaurant",), **FOUND)
    plant(conn, diner)
    raw = conn.execute("SELECT doc FROM tool WHERE id = 'diner-bot'").fetchone()[0]
    assert db.seed(conn, removed_trade(catalog)) == ["diner-bot"]
    assert "diner-bot" not in {t.id for t in db.read_catalog(conn).tools}
    row = quarantine.inspect(conn, keys(conn)[0], with_raw=True)
    assert row["raw"] == raw and row["reason"] == "catalog_conflict" and row["state"] == "quarantined"
    assert row["tool_id"] == "diner-bot" and row["contract_version"] == db.TOOL_CONTRACT_VERSION and row["quarantined_at"]
    assert "restaurant" not in row["details"] or "trade" in row["details"].casefold()


def test_a_record_that_no_longer_parses_is_kept_as_text(conn, catalog):
    conn.execute("INSERT INTO tool (id, name, status, doc, origin) VALUES ('old-shape', 'Old', 'pending_review', ?, 'discovered')", ('{"id": "old-shape", "legacy": 1}',))
    conn.commit()
    assert db.seed(conn, catalog) == ["old-shape"]
    row = quarantine.inspect(conn, keys(conn)[0], with_raw=True)
    assert row["reason"] == "schema_invalid" and json.loads(row["raw"])["legacy"] == 1


def test_repeated_startup_creates_no_second_archive(conn, catalog):
    plant(conn, tool("diner-bot", 20, [], trades=("restaurant",), **FOUND))
    smaller = removed_trade(catalog)
    db.seed(conn, smaller)
    for _ in range(3):
        assert db.seed(conn, smaller) == []
    assert len(keys(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM quarantine_audit WHERE action = 'quarantine'").fetchone()[0] == 1


def test_a_missing_price_is_not_a_reason_to_quarantine(conn, catalog):
    plant(conn, tool("no-price", None, [], **FOUND))
    assert db.seed(conn, catalog) == [] and keys(conn) == []
    assert "no-price" in {t.id for t in db.read_catalog(conn).tools}


def test_a_curated_duplicate_is_archived_with_a_link_and_never_merged(conn, catalog):
    plant(conn, tool("found-voice", 20, [], **FOUND).model_copy(update={"name": "Voice"}))
    db.seed(conn, catalog)
    row = quarantine.list_records(conn)[0]
    assert row["state"] == "archived_duplicate" and row["canonical_id"] == "voice" and row["reason"] == "curated_duplicate"
    curated = db.read_catalog(conn).tool("voice")
    assert curated.status == "verified" and curated.entry_monthly_usd.value == 100


def test_a_discovered_row_sharing_an_id_with_a_newly_curated_tool_is_archived_not_overwritten(conn, catalog):
    without = catalog.model_copy(update={"tools": [t for t in catalog.tools if t.id != "solo"]})
    db.seed(conn, without)
    plant(conn, tool("solo", 5, [], **FOUND))
    assert db.seed(conn, catalog) == ["solo"]
    row = quarantine.list_records(conn)[0]
    assert row["state"] == "archived_duplicate" and row["canonical_id"] == "solo"
    assert db.read_catalog(conn).tool("solo").entry_monthly_usd.value == 60
    assert db.read_catalog(conn).tool("solo").origin == "catalog"


def test_restore_is_refused_while_the_record_is_still_invalid_and_loses_nothing(conn, catalog):
    plant(conn, tool("diner-bot", 20, [], trades=("restaurant",), **FOUND))
    smaller = removed_trade(catalog)
    db.seed(conn, smaller)
    key = keys(conn)[0]
    before = quarantine.inspect(conn, key, with_raw=True)["raw"]
    outcome = quarantine.restore(conn, smaller, key)
    assert not outcome.ok and outcome.reason == "catalog_conflict"
    after = quarantine.inspect(conn, key, with_raw=True)
    assert after["raw"] == before and after["state"] == "quarantined"
    assert "diner-bot" not in {t.id for t in db.read_catalog(conn).tools}
    assert [a["outcome"] for a in after["audit"] if a["action"] == "restore"] == ["refused"]


def test_restore_after_the_catalog_is_corrected_returns_a_pending_discovered_tool(conn, catalog):
    plant(conn, tool("diner-bot", 20, [], trades=("restaurant",), **FOUND))
    db.seed(conn, removed_trade(catalog))
    key = keys(conn)[0]
    db.seed(conn, catalog)
    assert quarantine.revalidate(conn, catalog, key).ok
    assert quarantine.restore(conn, catalog, key).ok
    back = db.read_catalog(conn).tool("diner-bot")
    assert back.status == "pending_review" and back.origin == "discovered"
    row = quarantine.inspect(conn, key, with_raw=True)
    assert row["state"] == "restored" and row["restored_at"] and row["raw"]
    assert [a["outcome"] for a in row["audit"] if a["action"] == "restore"] == ["restored"]
    assert not quarantine.restore(conn, catalog, key).ok
    assert db.seed(conn, catalog) == []


def test_a_verified_record_comes_back_as_pending_never_verified(conn, catalog):
    plant(conn, tool("diner-bot", 20, [], trades=("restaurant",), **FOUND))
    db.seed(conn, removed_trade(catalog))
    db.seed(conn, catalog)
    key = keys(conn)[0]
    raw = json.loads(quarantine.inspect(conn, key, with_raw=True)["raw"])
    raw["status"] = "verified"
    conn.execute("UPDATE quarantine SET raw = ? WHERE key = ?", (json.dumps(raw), key))
    quarantine.restore(conn, catalog, key)
    assert db.read_catalog(conn).tool("diner-bot").status == "pending_review"


def test_restore_never_overwrites_an_active_tool(conn, catalog):
    plant(conn, tool("diner-bot", 20, [], trades=("restaurant",), **FOUND))
    db.seed(conn, removed_trade(catalog))
    db.seed(conn, catalog)
    key = keys(conn)[0]
    plant(conn, tool("diner-bot", 99, [], **FOUND))
    outcome = quarantine.restore(conn, catalog, key)
    assert not outcome.ok and outcome.reason == "active_id_conflict"
    assert db.read_catalog(conn).tool("diner-bot").entry_monthly_usd.value == 99


def test_restore_never_overwrites_a_curated_tool(conn, catalog):
    plant(conn, tool("found-voice", 20, [], **FOUND).model_copy(update={"name": "Voice"}))
    db.seed(conn, catalog)
    key = keys(conn)[0]
    outcome = quarantine.restore(conn, catalog, key)
    assert not outcome.ok and outcome.reason == "curated_duplicate" and outcome.canonical_id == "voice"
    assert db.read_catalog(conn).tool("voice").entry_monthly_usd.value == 100


def test_saved_plan_snapshots_stay_readable_after_a_quarantine(conn, catalog):
    plant(conn, tool("diner-bot", 20, [], trades=("restaurant",), **FOUND))
    snapshot = json.dumps({"tool_id": "diner-bot", "name": "Diner-Bot", "price": 20})
    conn.execute("INSERT INTO owner_session VALUES ('h', 'now', 'later', NULL)")
    conn.execute("INSERT INTO adoption_plan VALUES ('p1', 'h', 'req-0001', 'x', 'now', ?)", (snapshot,))
    conn.commit()
    db.seed(conn, removed_trade(catalog))
    assert conn.execute("SELECT doc FROM adoption_plan WHERE id = 'p1'").fetchone()[0] == snapshot


def test_the_command_lists_inspects_and_hides_raw_text_unless_asked(conn, catalog, tmp_path):
    plant(conn, tool("diner-bot", 20, [], trades=("restaurant",), **FOUND))
    db.seed(conn, removed_trade(catalog))
    db.seed(conn, catalog)
    key = keys(conn)[0]
    path = tmp_path / "q.db"
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(catalog.model_dump_json(), encoding="utf-8")
    base = ["--db", str(path), "--catalog", str(catalog_path)]

    def call(*args):
        out = io.StringIO()
        return quarantine.main(base + list(args), out), out.getvalue()

    code, text = call("list")
    assert code == 0 and key in text and "catalog_conflict" in text and "1 record(s)" in text
    code, text = call("inspect", key)
    assert code == 0 and '"raw"' not in text and "reason" in text
    assert '"raw"' in call("inspect", key, "--raw")[1]
    assert call("revalidate", key)[0] == 0
    code, text = call("restore", key)
    assert code == 0 and "pending_review" in text
    assert call("restore", key)[0] == 1
    assert call("inspect", "nope@0")[0] == 2
    assert quarantine.main(["--db", str(tmp_path / "missing.db"), "list"], io.StringIO()) == 2


def test_restore_is_refused_when_the_running_catalog_has_not_been_reseeded(conn, catalog):
    plant(conn, tool("diner-bot", 20, [], trades=("restaurant",), **FOUND))
    db.seed(conn, removed_trade(catalog))
    key = keys(conn)[0]
    outcome = quarantine.restore(conn, catalog, key)
    assert not outcome.ok and outcome.reason == "catalog_conflict" and "restart" in outcome.details
    assert db.read_catalog(conn)
