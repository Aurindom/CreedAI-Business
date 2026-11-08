import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .domains import identity
from .schemas import Catalog, Category, Facet, ProblemCard, Tool, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trade_alias (trade_id TEXT NOT NULL, alias TEXT NOT NULL, PRIMARY KEY (trade_id, alias));
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
CREATE TABLE IF NOT EXISTS account_owner (
    user_id TEXT PRIMARY KEY,
    owner_hash TEXT NOT NULL UNIQUE REFERENCES owner_session(token_hash),
    business_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS revoked_auth_session (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    revoked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS favourite_tool (
    user_id TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    PRIMARY KEY (user_id, tool_id)
);
CREATE TABLE IF NOT EXISTS chat_conversation (
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    recover_until TEXT,
    PRIMARY KEY (user_id, conversation_id)
);
CREATE TABLE IF NOT EXISTS chat_session_usage (
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    PRIMARY KEY (user_id, conversation_id, session_id)
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
CREATE TABLE IF NOT EXISTS quarantine (
    key TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL,
    raw TEXT NOT NULL,
    state TEXT NOT NULL,
    reason TEXT NOT NULL,
    details TEXT NOT NULL,
    canonical_id TEXT,
    contract_version TEXT NOT NULL,
    quarantined_at TEXT NOT NULL,
    restored_at TEXT
);
CREATE TABLE IF NOT EXISTS quarantine_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    at TEXT NOT NULL
);
"""
CATALOG = "catalog"
DISCOVERED = "discovered"
TOOL_CONTRACT_VERSION = "1.1.0"
QUARANTINED = "quarantined"
ARCHIVED = "archived_duplicate"
RESTORED = "restored"


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


def judge(doc: str, catalog: Catalog, reviewed_ids: set[str], reviewed_identity: dict[tuple[str, str], str]) -> tuple[str, str, str | None] | None:
    """Why a stored discovered tool can't stay active, as (reason, details, canonical id), or None when it can.

    The raw text is parsed here on purpose: a record from an older schema may not load as a Tool at all.
    Details name fields and rules only, never the stored values.
    """
    try:
        found = Tool.model_validate_json(doc)
    except ValidationError as exc:
        return "schema_invalid", _details(exc), None
    twin = reviewed_identity.get(identity(found)) or (found.id if found.id in reviewed_ids else None)
    if twin:
        return "curated_duplicate", "same product as a reviewed catalog tool", twin
    try:
        Catalog(trades=catalog.trades, categories=catalog.categories, problem_cards=[], tools=[found], facets=catalog.facets)
    except ValidationError as exc:
        return "catalog_conflict", _details(exc), None
    return None


def _details(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc']) or 'record'}: {e['msg'][:120]}" for e in exc.errors()[:5]]
    return "; ".join(parts)


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def quarantine_key(tool_id: str, doc: str) -> str:
    return f"{tool_id}@{hashlib.sha256(doc.encode('utf-8')).hexdigest()[:12]}"


def _park(conn: sqlite3.Connection, tool_id: str, doc: str, reason: str, details: str, canonical: str | None) -> None:
    """Copies a record into quarantine without touching the tool table. The caller owns the transaction."""
    key = quarantine_key(tool_id, doc)
    state = ARCHIVED if reason == "curated_duplicate" else QUARANTINED
    existing = conn.execute("SELECT state FROM quarantine WHERE key = ?", (key,)).fetchone()
    if existing and existing[0] != RESTORED:
        return
    if existing:
        conn.execute(
            "UPDATE quarantine SET state = ?, reason = ?, details = ?, canonical_id = ?, quarantined_at = ?, restored_at = NULL WHERE key = ?",
            (state, reason, details, canonical, now_text(), key),
        )
    else:
        conn.execute(
            "INSERT INTO quarantine (key, tool_id, raw, state, reason, details, canonical_id, contract_version, quarantined_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, tool_id, doc, state, reason, details, canonical, TOOL_CONTRACT_VERSION, now_text()),
        )
    conn.execute(
        "INSERT INTO quarantine_audit (key, action, outcome, reason, at) VALUES (?, 'quarantine', ?, ?, ?)",
        (key, state, reason, now_text()),
    )


def seed(conn: sqlite3.Connection, catalog: Catalog) -> list[str]:
    """Catalog file wins on every start, so a corrected vendor fact reaches the app on the next deploy.

    Only rows the catalog owns are replaced. Discovered tools survive a restart. A discovered tool the
    new catalog can no longer hold, for example one naming a business type that was removed, moves into
    the quarantine table with its original text and the reason, so the app still starts and nothing is
    lost. A discovered tool that now duplicates a reviewed catalog entry (same id, or same owner domain
    and name) is archived with a link to the reviewed id instead. Neither kind is read as part of the
    catalog, and a repeated start moves nothing twice. Returns the ids that left the active catalog.
    """
    reviewed_ids = {t.id for t in catalog.tools}
    reviewed_identity = {identity(t): t.id for t in catalog.tools}
    with conn:
        stored = conn.execute("SELECT id, doc FROM tool WHERE origin = ?", (DISCOVERED,)).fetchall()
        moved = []
        for tool_id, doc in stored:
            verdict = judge(doc, catalog, reviewed_ids, reviewed_identity)
            if verdict:
                _park(conn, tool_id, doc, *verdict)
                moved.append(tool_id)
        conn.executemany("DELETE FROM tool WHERE id = ? AND origin = ?", [(i, DISCOVERED) for i in moved])
        for table in ("trade_alias", "trade", "category", "problem_card", "facet"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM tool WHERE origin = ?", (CATALOG,))
        conn.executemany(
            "INSERT OR REPLACE INTO trade VALUES (?, ?)", [(t.id, t.name) for t in catalog.trades]
        )
        conn.executemany("INSERT INTO trade_alias (trade_id, alias) VALUES (?, ?)",
                         [(trade.id, alias) for trade in catalog.trades for alias in dict.fromkeys(trade.aliases)])
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
            [(t.id, t.name, t.status, _doc(t, CATALOG), CATALOG) for t in catalog.tools],
        )
    return moved


def _doc(tool: Tool, origin: str) -> str:
    return tool.model_copy(update={"origin": origin}).model_dump_json()


def add_discovered_tool(conn: sqlite3.Connection, tool: Tool) -> None:
    """Stores a tool found by discovery. It never replaces a reviewed catalog row and can't arrive verified,
    because a research candidate isn't a checked fact until someone reviews it."""
    if tool.status == "verified":
        raise ValueError(f"discovered tool {tool.id!r} cannot be stored as verified")
    with conn:
        put_discovered(conn, tool)


def put_discovered(conn: sqlite3.Connection, tool: Tool) -> None:
    """The write behind add_discovered_tool, for callers that already hold a transaction."""
    row = conn.execute("SELECT origin FROM tool WHERE id = ?", (tool.id,)).fetchone()
    if row and row[0] == CATALOG:
        raise ValueError(f"tool {tool.id!r} is already in the reviewed catalog")
    conn.execute(
        "INSERT OR REPLACE INTO tool (id, name, status, doc, origin) VALUES (?, ?, ?, ?, ?)",
        (tool.id, tool.name, tool.status, _doc(tool, DISCOVERED), DISCOVERED),
    )


def read_catalog(conn: sqlite3.Connection) -> Catalog:
    aliases: dict[str, list[str]] = {}
    for trade_id, alias in conn.execute("SELECT trade_id, alias FROM trade_alias ORDER BY alias"):
        aliases.setdefault(trade_id, []).append(alias)
    trades = [Trade(id=row[0], name=row[1], aliases=aliases.get(row[0], [])) for row in conn.execute("SELECT id, name FROM trade ORDER BY name")]
    categories = [Category(**json.loads(row[0])) for row in conn.execute("SELECT doc FROM category ORDER BY position")]
    cards = [ProblemCard(**json.loads(row[0])) for row in conn.execute("SELECT doc FROM problem_card ORDER BY id")]
    tools = [Tool(**{**json.loads(doc), "origin": origin}) for doc, origin in conn.execute("SELECT doc, origin FROM tool ORDER BY name")]
    facets = [Facet(**json.loads(row[0])) for row in conn.execute("SELECT doc FROM facet ORDER BY position")]
    return Catalog(trades=trades, categories=categories, problem_cards=cards, tools=tools, facets=facets)
