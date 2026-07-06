"""SQLite persistence for incomplete requests.

This is the ONE bounded exception to the no-persistent-storage rule.
Only requests stopped on a hard requirement gap after round 2 are written here.
Active pipeline runs are NEVER written here — in-memory only.

Contract ref: Agent-Contracts-Reference.md §5
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Database lives next to this file, inside the app/ directory.
_DB_PATH = Path(__file__).parent / "incomplete_requests.db"
_TTL_HOURS = 48


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS incomplete_requests (
            request_id  TEXT PRIMARY KEY,
            payload     TEXT NOT NULL,
            expires_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()


def purge_expired() -> int:
    """Delete all rows whose TTL has passed.

    Called at the start of every Orchestrator session — check-on-access,
    no background scheduler.

    Returns the number of rows deleted.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        _ensure_table(conn)
        cursor = conn.execute(
            "DELETE FROM incomplete_requests WHERE expires_at < ?", (now,)
        )
        conn.commit()
        return cursor.rowcount


def save_incomplete(request_id: str, payload: dict) -> str:
    """Persist an incomplete request with a 48-hour TTL.

    Returns the expires_at ISO-8601 string (for returning to the frontend).
    Raises sqlite3.IntegrityError if request_id already exists; callers
    should use upsert logic if re-saves are needed.
    """
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=_TTL_HOURS)
    ).isoformat()
    with _connect() as conn:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO incomplete_requests (request_id, payload, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(request_id) DO UPDATE SET
                payload    = excluded.payload,
                expires_at = excluded.expires_at
            """,
            (request_id, json.dumps(payload), expires_at),
        )
        conn.commit()
    return expires_at


def load_incomplete(request_id: str) -> dict | None:
    """Return the stored payload for a request, or None if expired/not found."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT payload FROM incomplete_requests WHERE request_id = ? AND expires_at >= ?",
            (request_id, now),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["payload"])


def delete_incomplete(request_id: str) -> None:
    """Remove a request after successful completion or explicit cancellation."""
    with _connect() as conn:
        _ensure_table(conn)
        conn.execute(
            "DELETE FROM incomplete_requests WHERE request_id = ?", (request_id,)
        )
        conn.commit()
