"""SQLite-backed outbound queue and inbound deduplication ledger."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .protocol import Message, decode_frame, encode_frame


class Outbox:
    def __init__(self, path: str | Path) -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.RLock()
        self._db.execute("PRAGMA busy_timeout = 2000")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS outbox ("
            "id TEXT PRIMARY KEY, frame BLOB NOT NULL, acked INTEGER NOT NULL DEFAULT 0)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS inbox ("
            "id TEXT PRIMARY KEY, posted INTEGER NOT NULL DEFAULT 0)"
        )
        self._db.commit()

    def enqueue(self, msg: Message) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO outbox (id, frame) VALUES (?, ?)",
                (msg.id, encode_frame(msg)),
            )
            self._db.commit()

    def pending(self, limit: int = 200) -> list[Message]:
        with self._lock:
            rows = self._db.execute(
                "SELECT frame FROM outbox WHERE acked = 0 ORDER BY rowid LIMIT ?", (limit,)
            ).fetchall()
        return [decode_frame(frame) for (frame,) in rows]

    def ack(self, message_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE outbox SET acked = 1 WHERE id = ?", (message_id,))
            self._db.commit()

    def register_incoming(self, message_id: str) -> bool:
        """True if this message is already marked posted locally."""
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO inbox (id) VALUES (?)", (message_id,))
            row = self._db.execute("SELECT posted FROM inbox WHERE id = ?", (message_id,)).fetchone()
            self._db.commit()
            return bool(row[0])

    def mark_posted(self, message_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE inbox SET posted = 1 WHERE id = ?", (message_id,))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> "Outbox":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
