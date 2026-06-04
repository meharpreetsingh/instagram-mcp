import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def init_db(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_schema(conn)
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS threads (
            thread_id     TEXT PRIMARY KEY,
            thread_title  TEXT,
            is_group      INTEGER DEFAULT 0,
            participants  TEXT,
            last_synced_at TEXT,
            updated_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            message_id  TEXT PRIMARY KEY,
            thread_id   TEXT NOT NULL,
            sender      TEXT,
            sender_id   TEXT,
            text        TEXT,
            item_type   TEXT,
            timestamp   TEXT,
            fetched_at  TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (thread_id) REFERENCES threads(thread_id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            text,
            sender,
            thread_id,
            content=messages,
            content_rowid=rowid
        );

        CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, text, sender, thread_id)
            VALUES (new.rowid, new.text, new.sender, new.thread_id);
        END;

        CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, text, sender, thread_id)
            VALUES ('delete', old.rowid, old.text, old.sender, old.thread_id);
            INSERT INTO messages_fts(rowid, text, sender, thread_id)
            VALUES (new.rowid, new.text, new.sender, new.thread_id);
        END;
    """)
    conn.commit()


def upsert_thread(conn: sqlite3.Connection, thread: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO threads (thread_id, thread_title, is_group, participants, last_synced_at, updated_at)
        VALUES (:thread_id, :thread_title, :is_group, :participants, :last_synced_at, :updated_at)
        ON CONFLICT(thread_id) DO UPDATE SET
            thread_title   = excluded.thread_title,
            is_group       = excluded.is_group,
            participants   = excluded.participants,
            last_synced_at = excluded.last_synced_at,
            updated_at     = excluded.updated_at
        """,
        {
            "thread_id": thread["thread_id"],
            "thread_title": thread.get("thread_title"),
            "is_group": int(thread.get("is_group", False)),
            "participants": json.dumps(thread.get("participants", [])),
            "last_synced_at": now,
            "updated_at": now,
        },
    )
    conn.commit()


def upsert_messages(conn: sqlite3.Connection, thread_id: str, messages: list[dict]) -> int:
    inserted = 0
    for msg in messages:
        if not msg.get("message_id"):
            continue
        existing = conn.execute(
            "SELECT message_id FROM messages WHERE message_id = ?", (msg["message_id"],)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO messages
                (message_id, thread_id, sender, sender_id, text, item_type, timestamp)
            VALUES (:message_id, :thread_id, :sender, :sender_id, :text, :item_type, :timestamp)
            """,
            {
                "message_id": msg["message_id"],
                "thread_id": thread_id,
                "sender": msg.get("sender"),
                "sender_id": msg.get("sender_id"),
                "text": msg.get("text"),
                "item_type": msg.get("item_type"),
                "timestamp": msg.get("timestamp"),
            },
        )
        inserted += 1
    conn.commit()
    return inserted


def get_threads(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT thread_id, thread_title, is_group, participants, last_synced_at FROM threads ORDER BY updated_at DESC"
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["participants"] = json.loads(d["participants"] or "[]")
        d["is_group"] = bool(d["is_group"])
        result.append(d)
    return result


def get_thread_messages(conn: sqlite3.Connection, thread_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT message_id, thread_id, sender, sender_id, text, item_type, timestamp FROM messages WHERE thread_id = ? ORDER BY timestamp ASC",
        (thread_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def search_messages(
    conn: sqlite3.Connection, query: str, thread_id: Optional[str] = None, limit: int = 20
) -> list[dict]:
    if thread_id:
        rows = conn.execute(
            """
            SELECT m.message_id, m.thread_id, m.sender, m.text, m.timestamp
            FROM messages_fts f
            JOIN messages m ON m.rowid = f.rowid
            WHERE messages_fts MATCH ? AND m.thread_id = ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, thread_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT m.message_id, m.thread_id, m.sender, m.text, m.timestamp
            FROM messages_fts f
            JOIN messages m ON m.rowid = f.rowid
            WHERE messages_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    return [dict(row) for row in rows]
