import hashlib
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta

SESSION_DAYS = 30


class AccessDenied(Exception):
    """Raised for a missing, unknown, expired or revoked owner token. The message never repeats the token."""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn: sqlite3.Connection, now: datetime, days: int = SESSION_DAYS) -> tuple[str, datetime]:
    """Only the hash is stored, so someone holding a copy of the database still can't act as an owner."""
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(days=days)
    with conn:
        conn.execute("DELETE FROM owner_session WHERE expires_at < ? AND token_hash NOT IN (SELECT owner_hash FROM adoption_plan)", (now.isoformat(),))
        conn.execute(
            "INSERT INTO owner_session (token_hash, created_at, expires_at) VALUES (?, ?, ?)",
            (token_hash(token), now.isoformat(), expires.isoformat()),
        )
    return token, expires


def owner_for(conn: sqlite3.Connection, token: str | None, now: datetime) -> str:
    if not token:
        raise AccessDenied("No private session was given")
    if conn.execute('SELECT 1 FROM account_owner WHERE owner_hash=?', (token_hash(token),)).fetchone():
        raise AccessDenied('Account ownership is not a browser-session credential')
    row = conn.execute("SELECT expires_at, revoked_at FROM owner_session WHERE token_hash = ?", (token_hash(token),)).fetchone()
    if row is None or row[1] is not None or datetime.fromisoformat(row[0]) <= now:
        raise AccessDenied("This private session is unknown, has ended or was closed")
    return token_hash(token)


def revoke(conn: sqlite3.Connection, owner: str, now: datetime) -> None:
    with conn:
        conn.execute("UPDATE owner_session SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL", (now.isoformat(), owner))


def bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.casefold() != "bearer":
        return None
    return value.strip() or None


def account_owner(conn, user_id, now):
    """One owner workspace per verified Supabase subject. No browser token issued."""
    row = conn.execute('SELECT owner_hash, business_id FROM account_owner WHERE user_id = ?', (user_id,)).fetchone()
    if row:
        return row[0], row[1]
    owner = token_hash(secrets.token_urlsafe(32))
    business = str(uuid.uuid4())
    with conn:
        # Legacy FK anchor only; its hash is not an account credential.
        conn.execute('INSERT OR IGNORE INTO owner_session(token_hash, created_at, expires_at) VALUES(?,?,?)',
                     (owner, now.isoformat(), '9999-12-31T00:00:00+00:00'))
        conn.execute('INSERT OR IGNORE INTO account_owner VALUES(?,?,?)', (user_id, owner, business))
    row = conn.execute('SELECT owner_hash,business_id FROM account_owner WHERE user_id=?', (user_id,)).fetchone()
    return row[0], row[1]


def claim_legacy(conn, user_id, legacy_token, now):
    """Explicit possession proof; migration and revocation commit together."""
    legacy = owner_for(conn, legacy_token, now)
    owner, _ = account_owner(conn, user_id, now)
    with conn:
        # Recheck after acquiring the SQLite write transaction, not before it.
        conn.execute('UPDATE owner_session SET revoked_at=revoked_at WHERE token_hash=?', (legacy,))
        owner_for(conn, legacy_token, now)
        rows = conn.execute('SELECT id FROM adoption_plan WHERE owner_hash=?', (legacy,)).fetchall()
        for (plan_id,) in rows:
            conn.execute('UPDATE adoption_plan SET owner_hash=?, request_id=? WHERE id=? AND owner_hash=?',
                         (owner, 'import:' + plan_id, plan_id, legacy))
        conn.execute('UPDATE owner_session SET revoked_at=? WHERE token_hash=?', (now.isoformat(), legacy))
    return len(rows)
