"""SQLite storage for leads and notification feed."""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import settings

_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,             -- telegram | web_form
    text TEXT NOT NULL,
    type TEXT NOT NULL,               -- price_question | support | complaint | partnership | spam | other
    urgency TEXT NOT NULL,            -- low | medium | high
    name TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',  -- new | in_progress | done
    llm_provider TEXT NOT NULL DEFAULT '',
    processing_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at);
CREATE INDEX IF NOT EXISTS idx_leads_type ON leads(type);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    channel TEXT NOT NULL,            -- telegram | log
    recipient TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    lead_id INTEGER
);
"""


def _connect() -> sqlite3.Connection:
    import os

    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    with _LOCK:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(_SCHEMA)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def insert_lead(
    *,
    source: str,
    text: str,
    type_: str,
    urgency: str,
    name: str,
    contact: str,
    summary: str,
    llm_provider: str,
    processing_ms: int,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO leads
               (created_at, source, text, type, urgency, name, contact, summary, status, llm_provider, processing_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
            (utcnow(), source, text, type_, urgency, name, contact, summary, llm_provider, processing_ms),
        )
        return int(cur.lastrowid)


def list_leads(
    *,
    type_: str | None = None,
    urgency: str | None = None,
    status: str | None = None,
    order: str = "desc",
    limit: int = 500,
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if type_:
        clauses.append("type = ?")
        params.append(type_)
    if urgency:
        clauses.append("urgency = ?")
        params.append(urgency)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    direction = "ASC" if order == "asc" else "DESC"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM leads {where} ORDER BY created_at {direction}, id {direction} LIMIT ?", params
        ).fetchall()
        return [dict(r) for r in rows]


def update_lead_status(lead_id: int, status: str) -> bool:
    with connect() as conn:
        cur = conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
        return cur.rowcount > 0


def get_lead(lead_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else None


def insert_notification(*, channel: str, recipient: str, text: str, lead_id: int | None = None) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO notifications (created_at, channel, recipient, text, lead_id) VALUES (?, ?, ?, ?, ?)",
            (utcnow(), channel, recipient, text, lead_id),
        )
        return int(cur.lastrowid)


def list_notifications(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def stats() -> dict[str, Any]:
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
        by_status = dict(conn.execute("SELECT status, COUNT(*) c FROM leads GROUP BY status").fetchall())
        by_urgency = dict(conn.execute("SELECT urgency, COUNT(*) c FROM leads GROUP BY urgency").fetchall())
        avg_ms = conn.execute("SELECT AVG(processing_ms) a FROM leads WHERE processing_ms > 0").fetchone()["a"]
    return {
        "total": total,
        "by_status": by_status,
        "by_urgency": by_urgency,
        "avg_processing_ms": round(avg_ms) if avg_ms is not None else 0,
    }
