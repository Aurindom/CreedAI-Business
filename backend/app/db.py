import json
import sqlite3
from pathlib import Path

from .schemas import Catalog, Category, Facet, ProblemCard, Tool, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS category (id TEXT PRIMARY KEY, position INTEGER NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS problem_card (id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facet (id TEXT PRIMARY KEY, position INTEGER NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tool (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    doc TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'catalog'
);
CREATE TABLE IF NOT EXISTS owner_session (
    token_hash TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS adoption_plan (
    id TEXT PRIMARY KEY,
    owner_hash TEXT NOT NULL REFERENCES owner_session(token_hash),
    request_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    doc TEXT NOT NULL,
    UNIQUE (owner_hash, request_id)
);
"""
CATALOG = "catalog"
DISCOVERED = "discovered"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tool)")}
    if "origin" not in columns:
        with conn:
            conn.execute(f"ALTER TABLE tool ADD COLUMN origin TEXT NOT NULL DEFAULT '{CATALOG}'")
    return conn


def load_catalog_file(path: Path) -> Catalog:
    if not path.exists():
        raise FileNotFoundError(f"catalog file not found: {path}")
    return Catalog.model_validate_json(path.read_text(encoding="utf-8"))


def seed(conn: sqlite3.Connection, catalog: Catalog) -> None:
    """Catalog file wins on every start, so a corrected vendor fact reaches the app on the next deploy.

    Only rows the catalog owns are replaced. Discovered tools survive a restart, and a discovered
    tool that later appears in the catalog file is taken over by the reviewed catalog entry.
    """
    with conn:
        for table in ("trade", "category", "problem_card", "facet"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM tool WHERE origin = ?", (CATALOG,))
        conn.executemany(
            "INSERT OR REPLACE INTO trade VALUES (?, ?)", [(t.id, t.name) for t in catalog.trades]
        )
        conn.executemany(
            "INSERT OR REPLACE INTO category VALUES (?, ?, ?)",
            [(c.id, i, c.model_dump_json()) for i, c in enumerate(catalog.categories)],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO problem_card VALUES (?, ?)",
            [(p.id, p.model_dump_json()) for p in catalog.problem_cards],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO facet VALUES (?, ?, ?)",
            [(f.id, i, f.model_dump_json()) for i, f in enumerate(catalog.facets)],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO tool (id, name, status, doc, origin) VALUES (?, ?, ?, ?, ?)",
            [(t.id, t.name, t.status, t.model_dump_json(), CATALOG) for t in catalog.tools],
        )


def add_discovered_tool(conn: sqlite3.Connection, tool: Tool) -> None:
    """Stores a tool found by discovery. It never replaces a reviewed catalog row and can't arrive verified,
    because a research candidate isn't a checked fact until someone reviews it."""
    if tool.status == "verified":
        raise ValueError(f"discovered tool {tool.id!r} cannot be stored as verified")
    with conn:
        row = conn.execute("SELECT origin FROM tool WHERE id = ?", (tool.id,)).fetchone()
        if row and row[0] == CATALOG:
            raise ValueError(f"tool {tool.id!r} is already in the reviewed catalog")
        conn.execute(
            "INSERT OR REPLACE INTO tool (id, name, status, doc, origin) VALUES (?, ?, ?, ?, ?)",
            (tool.id, tool.name, tool.status, tool.model_dump_json(), DISCOVERED),
        )


def read_catalog(conn: sqlite3.Connection) -> Catalog:
    trades = [Trade(id=row[0], name=row[1]) for row in conn.execute("SELECT id, name FROM trade ORDER BY name")]
    categories = [Category(**json.loads(row[0])) for row in conn.execute("SELECT doc FROM category ORDER BY position")]
    cards = [ProblemCard(**json.loads(row[0])) for row in conn.execute("SELECT doc FROM problem_card ORDER BY id")]
    tools = [Tool(**json.loads(row[0])) for row in conn.execute("SELECT doc FROM tool ORDER BY name")]
    facets = [Facet(**json.loads(row[0])) for row in conn.execute("SELECT doc FROM facet ORDER BY position")]
    return Catalog(trades=trades, categories=categories, problem_cards=cards, tools=tools, facets=facets)
