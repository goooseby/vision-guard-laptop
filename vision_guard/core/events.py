from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from vision_guard.config import AppConfig
from vision_guard.core.models import EventRecord
from vision_guard.storage.database import EventDatabase


@dataclass(slots=True)
class DeleteResult:
    requested: int
    deleted_records: int
    deleted_files: int
    freed_bytes: int
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "deleted_records": self.deleted_records,
            "deleted_files": self.deleted_files,
            "freed_bytes": self.freed_bytes,
            "errors": self.errors,
        }


class EventService:
    def __init__(self, *, database: EventDatabase, project_root: Path, config: AppConfig):
        self.database = database
        self.project_root = project_root
        self.config = config

    def set_config(self, config: AppConfig) -> None:
        self.config = config

    def list_events(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        date_from, date_to = self._date_range(filters)
        events = self.database.list_events(
            limit=int(filters.get("limit") or 500),
            date_from=date_from,
            date_to=date_to,
        )
        return [self.enrich_event(event) for event in events]

    def enrich_event(self, event: EventRecord) -> dict[str, Any]:
        video_path = self.resolve_path(event.video_path)
        thumbnail_path = self.resolve_path(event.thumbnail_path)
        video_size = file_size(video_path)
        thumbnail_size = file_size(thumbnail_path)
        payload = event.to_dict()
        payload.update(
            {
                "video_exists": video_path.exists() if event.video_path else False,
                "thumbnail_exists": thumbnail_path.exists() if event.thumbnail_path else False,
                "video_size_bytes": video_size,
                "thumbnail_size_bytes": thumbnail_size,
                "total_size_bytes": video_size + thumbnail_size,
                "file_name": video_path.name if event.video_path else "",
            }
        )
        return payload

    def stats(self) -> dict[str, Any]:
        events = self.database.list_events(limit=100000)
        video_bytes = 0
        thumbnail_bytes = 0
        missing_files = 0
        for event in events:
            video_path = self.resolve_path(event.video_path)
            thumbnail_path = self.resolve_path(event.thumbnail_path)
            if event.video_path and not video_path.exists():
                missing_files += 1
            if event.thumbnail_path and not thumbnail_path.exists():
                missing_files += 1
            video_bytes += file_size(video_path)
            thumbnail_bytes += file_size(thumbnail_path)
        storage_dir = self.config.storage_dir(self.project_root)
        usage = shutil.disk_usage(storage_dir if storage_dir.exists() else self.project_root)
        counts = self.database.stats()
        return {
            **counts,
            "video_bytes": video_bytes,
            "thumbnail_bytes": thumbnail_bytes,
            "database_bytes": file_size(self.database.db_path),
            "total_bytes": video_bytes + thumbnail_bytes + file_size(self.database.db_path),
            "missing_files": missing_files,
            "storage_path": storage_dir.as_posix(),
            "disk_free_bytes": usage.free,
            "disk_total_bytes": usage.total,
        }

    def delete_events(self, event_ids: list[str]) -> DeleteResult:
        result = DeleteResult(
            requested=len(event_ids),
            deleted_records=0,
            deleted_files=0,
            freed_bytes=0,
            errors=[],
        )
        for event_id in event_ids:
            event = self.database.get_event(event_id)
            if event is None:
                result.errors.append(f"{event_id}: 事件不存在")
                continue
            for path in [self.resolve_path(event.video_path), self.resolve_path(event.thumbnail_path)]:
                if not path or not path.exists() or not path.is_file():
                    continue
                try:
                    size = path.stat().st_size
                    path.unlink()
                    result.deleted_files += 1
                    result.freed_bytes += size
                except OSError as exc:
                    result.errors.append(f"{event_id}: 删除文件失败 {path.name}: {exc}")
            if self.database.delete_event(event_id):
                result.deleted_records += 1
        return result

    def cleanup(self, *, mode: str = "configured") -> dict[str, Any]:
        events = self.database.list_events(limit=100000)
        candidates: list[EventRecord] = []

        if mode in {"configured", "retention"}:
            cutoff = datetime.now().astimezone() - timedelta(days=self.config.retention.retention_days)
            candidates.extend(event for event in events if parse_dt(event.triggered_at) < cutoff)

        if mode in {"configured", "capacity"}:
            max_bytes = int(self.config.retention.max_storage_gb * 1024 * 1024 * 1024)
            total = sum(self.enrich_event(event)["total_size_bytes"] for event in events)
            if total > max_bytes:
                seen = {event.event_id for event in candidates}
                for event in sorted(events, key=lambda item: item.triggered_at):
                    if total <= max_bytes:
                        break
                    if event.event_id in seen:
                        continue
                    candidates.append(event)
                    seen.add(event.event_id)
                    total -= self.enrich_event(event)["total_size_bytes"]

        unique_ids = list(dict.fromkeys(event.event_id for event in candidates))
        result = self.delete_events(unique_ids)
        return {"candidates": len(unique_ids), "result": result.to_dict(), "stats": self.stats()}

    def resolve_path(self, value: str) -> Path:
        if not value:
            return Path()
        path = Path(value)
        if path.is_absolute():
            return path
        return self.project_root / path

    def _date_range(self, filters: dict[str, Any]) -> tuple[str | None, str | None]:
        preset = filters.get("preset")
        now = datetime.now().astimezone()
        if preset == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start.isoformat(), None
        if preset == "7d":
            return (now - timedelta(days=7)).isoformat(), None
        if preset == "30d":
            return (now - timedelta(days=30)).isoformat(), None
        return filters.get("date_from") or None, filters.get("date_to") or None


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.exists() and path.is_file() else 0
    except OSError:
        return 0


def parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=datetime.now().astimezone().tzinfo)
