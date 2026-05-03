from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from vision_guard.config import AppConfig
from vision_guard.core.engine import MonitorEngine
from vision_guard.core.events import EventService
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


def test_motion_roi_must_stay_inside_frame():
    with pytest.raises(ValueError):
        AppConfig.model_validate(
            {
                "motion": {
                    "roi_enabled": True,
                    "roi_x": 0.8,
                    "roi_y": 0,
                    "roi_width": 0.4,
                    "roi_height": 1,
                }
            }
        )


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


def test_motion_analysis_respects_roi():
    root = runtime_dir()
    config = AppConfig()
    config.motion.motion_sensitivity = 10
    config.motion.min_contour_area = 5
    config.motion.threshold_value = 10
    config.motion.roi_enabled = True
    config.motion.roi_x = 0.5
    config.motion.roi_y = 0.5
    config.motion.roi_width = 0.5
    config.motion.roi_height = 0.5
    database = EventDatabase(root / "events.sqlite3")
    engine = MonitorEngine(config=config, database=database, project_root=root)

    previous = np.zeros((100, 100), dtype=np.uint8)
    outside_only = previous.copy()
    outside_only[10:35, 10:35] = 255
    inside = previous.copy()
    inside[60:85, 60:85] = 255

    outside_motion = engine._analyze_motion(previous, outside_only)
    inside_motion = engine._analyze_motion(previous, inside)

    assert outside_motion["score"] == 0
    assert inside_motion["score"] > 0
    assert inside_motion["boxes"][0]["x"] >= 0.5
    database.close()
    shutil.rmtree(root)


def test_event_service_deletes_files_and_record():
    root = runtime_dir()
    config = AppConfig()
    database = EventDatabase(root / "storage" / "events.sqlite3")
    service = EventService(database=database, project_root=root, config=config)
    storage = root / "storage"
    storage.mkdir(exist_ok=True)
    video = storage / "EVENT_TEST.mp4"
    thumb = storage / "EVENT_TEST.jpg"
    video.write_bytes(b"video")
    thumb.write_bytes(b"thumb")
    now = datetime.now().astimezone().isoformat()
    database.create_event(
        EventRecord(
            id=None,
            event_id="EVENT_TEST",
            triggered_at=now,
            label="画面移动",
            video_path="storage/EVENT_TEST.mp4",
            thumbnail_path="storage/EVENT_TEST.jpg",
            pre_record_seconds=1,
            post_record_seconds=2,
            duration_seconds=3,
            motion_score=100,
            status=EventStatus.SAVED.value,
            error=None,
            created_at=now,
        )
    )

    result = service.delete_events(["EVENT_TEST"])

    assert result.deleted_records == 1
    assert result.deleted_files == 2
    assert result.freed_bytes == 10
    assert database.get_event("EVENT_TEST") is None
    assert not video.exists()
    assert not thumb.exists()
    database.close()
    shutil.rmtree(root)


def test_event_service_retention_cleanup():
    root = runtime_dir()
    config = AppConfig()
    config.retention.retention_days = 7
    database = EventDatabase(root / "storage" / "events.sqlite3")
    service = EventService(database=database, project_root=root, config=config)
    storage = root / "storage"
    storage.mkdir(exist_ok=True)
    old_time = (datetime.now().astimezone() - timedelta(days=14)).isoformat()
    video = storage / "OLD.mp4"
    video.write_bytes(b"old")
    database.create_event(
        EventRecord(
            id=None,
            event_id="OLD",
            triggered_at=old_time,
            label="画面移动",
            video_path="storage/OLD.mp4",
            thumbnail_path="",
            pre_record_seconds=0,
            post_record_seconds=1,
            duration_seconds=1,
            motion_score=100,
            status=EventStatus.SAVED.value,
            error=None,
            created_at=old_time,
        )
    )

    result = service.cleanup(mode="retention")

    assert result["result"]["deleted_records"] == 1
    assert database.get_event("OLD") is None
    assert not video.exists()
    database.close()
    shutil.rmtree(root)
