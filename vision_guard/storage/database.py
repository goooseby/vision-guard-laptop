from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from vision_guard.core.models import EventRecord, EventStatus


class EventDatabase:
    """Thin SQLite wrapper for event metadata.

    SQLite connections are not freely shareable across threads by default. The
    connection is opened with `check_same_thread=False` and protected with an
    `RLock` because UI calls and the monitor thread may access event metadata at
    the same time.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_event(self, record: EventRecord) -> EventRecord:
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO events (
                    event_id, triggered_at, label, video_path, thumbnail_path,
                    pre_record_seconds, post_record_seconds, duration_seconds,
                    motion_score, status, error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.event_id,
                    record.triggered_at,
                    record.label,
                    record.video_path,
                    record.thumbnail_path,
                    record.pre_record_seconds,
                    record.post_record_seconds,
                    record.duration_seconds,
                    record.motion_score,
                    record.status,
                    record.error,
                    record.created_at,
                ),
            )
            self._conn.commit()
            record.id = int(cursor.lastrowid)
            return record

    def mark_failed(
        self,
        *,
        event_id: str,
        triggered_at: str,
        label: str,
        motion_score: float,
        error: str,
    ) -> EventRecord:
        record = EventRecord(
            id=None,
            event_id=event_id,
            triggered_at=triggered_at,
            label=label,
            video_path="",
            thumbnail_path="",
            pre_record_seconds=0,
            post_record_seconds=0,
            duration_seconds=0,
            motion_score=motion_score,
            status=EventStatus.FAILED.value,
            error=error,
            created_at=datetime.now().astimezone().isoformat(),
        )
        return self.create_event(record)

    def list_events(
        self,
        limit: int = 500,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[EventRecord]:
        """List newest events first, with optional ISO timestamp filtering."""
        where: list[str] = []
        params: list[object] = []
        if date_from:
            where.append("triggered_at >= ?")
            params.append(date_from)
        if date_to:
            where.append("triggered_at <= ?")
            params.append(date_to)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT * FROM events
                {where_sql}
                ORDER BY triggered_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [row_to_event(row) for row in rows]

    def get_event(self, event_id: str) -> EventRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return row_to_event(row) if row else None

    def delete_event(self, event_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS count FROM events GROUP BY status"
            ).fetchall()
            total = self._conn.execute("SELECT COUNT(*) AS count FROM events").fetchone()["count"]
        result = {"total": int(total), "saved": 0, "partial": 0, "failed": 0}
        for row in rows:
            result[str(row["status"])] = int(row["count"])
        return result

    def _init_schema(self) -> None:
        """Create the event table and timestamp index if this is a new database."""
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    triggered_at TEXT NOT NULL,
                    label TEXT NOT NULL,
                    video_path TEXT NOT NULL,
                    thumbnail_path TEXT NOT NULL,
                    pre_record_seconds REAL NOT NULL DEFAULT 0,
                    post_record_seconds REAL NOT NULL DEFAULT 0,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    motion_score REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_triggered_at ON events(triggered_at DESC)"
            )
            self._conn.commit()


def row_to_event(row: sqlite3.Row) -> EventRecord:
    return EventRecord(
        id=int(row["id"]),
        event_id=str(row["event_id"]),
        triggered_at=str(row["triggered_at"]),
        label=str(row["label"]),
        video_path=str(row["video_path"]),
        thumbnail_path=str(row["thumbnail_path"]),
        pre_record_seconds=float(row["pre_record_seconds"]),
        post_record_seconds=float(row["post_record_seconds"]),
        duration_seconds=float(row["duration_seconds"]),
        motion_score=float(row["motion_score"]),
        status=str(row["status"]),
        error=row["error"],
        created_at=str(row["created_at"]),
    )


def iter_existing_media(events: Iterable[EventRecord]) -> Iterable[Path]:
    for event in events:
        if event.video_path:
            yield Path(event.video_path)
        if event.thumbnail_path:
            yield Path(event.thumbnail_path)
