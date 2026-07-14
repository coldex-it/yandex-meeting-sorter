from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class StateStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS processed_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT NOT NULL,
                disk_paths TEXT,
                details TEXT,
                processed_at TEXT NOT NULL,
                UNIQUE(uid),
                UNIQUE(message_id)
            );
            """
        )
        self.connection.commit()

    def get_last_uid(self) -> int | None:
        row = self.connection.execute(
            "SELECT value FROM state WHERE key = 'last_uid'"
        ).fetchone()
        return int(row[0]) if row else None

    def set_last_uid(self, uid: int) -> None:
        self.connection.execute(
            """
            INSERT INTO state(key, value) VALUES('last_uid', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(uid),),
        )
        self.connection.commit()

    def is_processed(self, uid: int, message_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM processed_messages WHERE uid = ? OR message_id = ? LIMIT 1",
            (uid, message_id),
        ).fetchone()
        return row is not None

    def list_uids_by_status(self, status: str) -> list[int]:
        rows = self.connection.execute(
            "SELECT uid FROM processed_messages WHERE status = ? ORDER BY uid",
            (status,),
        ).fetchall()
        return [int(row[0]) for row in rows]

    def record(
        self,
        uid: int,
        message_id: str,
        subject: str,
        status: str,
        disk_paths: list[str] | None = None,
        details: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO processed_messages(
                uid, message_id, subject, status, disk_paths, details, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                message_id = excluded.message_id,
                subject = excluded.subject,
                status = excluded.status,
                disk_paths = excluded.disk_paths,
                details = excluded.details,
                processed_at = excluded.processed_at
            """,
            (
                uid,
                message_id,
                subject,
                status,
                "\n".join(disk_paths or []),
                details,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.connection.commit()
