from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path

from vision_guard.config import AppConfig
from vision_guard.core.models import EventRecord, EventStatus
from vision_guard.storage.database import EventDatabase


def runtime_dir() -> Path:
    root = Path("tests_runtime")
    root.mkdir(exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    return path


def test_config_is_created_from_defaults():
    root = runtime_dir()
    config = AppConfig.load(root)

    assert config.camera.camera_id == 0
    assert (root / "config.json").exists()
    assert config.storage_dir(root) == root / "storage"
    shutil.rmtree(root)


def test_database_round_trip():
    root = runtime_dir()
    database = EventDatabase(root / "events.sqlite3")
    now = datetime.now().astimezone().isoformat()

    created = database.create_event(
        EventRecord(
            id=None,
            event_id="EVENT_TEST",
            triggered_at=now,
            label="画面移动",
            video_path="storage/EVENT_TEST.mp4",
            thumbnail_path="storage/EVENT_TEST.jpg",
            pre_record_seconds=3,
            post_record_seconds=10,
            duration_seconds=13,
            motion_score=4200,
            status=EventStatus.SAVED.value,
            error=None,
            created_at=now,
        )
    )

    assert created.id is not None
    assert database.stats()["total"] == 1
    assert database.get_event("EVENT_TEST").video_path.endswith(".mp4")
    assert database.list_events()[0].event_id == "EVENT_TEST"
    database.close()
    shutil.rmtree(root)
