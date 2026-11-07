import json
import sqlite3
from pathlib import Path

from .schemas import Catalog, Category, ProblemCard, Tool, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS category (id TEXT PRIMARY KEY, position INTEGER NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS problem_card (id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tool (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    doc TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def load_catalog_file(path: Path) -> Catalog:
    if not path.exists():
        raise FileNotFoundError(f"catalog file not found: {path}")
    return Catalog.model_validate_json(path.read_text(encoding="utf-8"))


def seed(conn: sqlite3.Connection, catalog: Catalog) -> None:
    """Catalog file wins on every start, so a corrected vendor fact reaches the app on the next deploy."""
    with conn:
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
            "INSERT OR REPLACE INTO tool VALUES (?, ?, ?, ?)",
            [(t.id, t.name, t.status, t.model_dump_json()) for t in catalog.tools],
        )


def read_catalog(conn: sqlite3.Connection) -> Catalog:
    trades = [Trade(id=row[0], name=row[1]) for row in conn.execute("SELECT id, name FROM trade ORDER BY name")]
    categories = [Category(**json.loads(row[0])) for row in conn.execute("SELECT doc FROM category ORDER BY position")]
    cards = [ProblemCard(**json.loads(row[0])) for row in conn.execute("SELECT doc FROM problem_card ORDER BY id")]
    tools = [Tool(**json.loads(row[0])) for row in conn.execute("SELECT doc FROM tool ORDER BY name")]
    return Catalog(trades=trades, categories=categories, problem_cards=cards, tools=tools)
