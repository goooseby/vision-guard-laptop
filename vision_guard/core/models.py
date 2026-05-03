from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class EngineState(str, Enum):
    DISARMED = "disarmed"
    ARMING = "arming"
    ARMED = "armed"
    TRIGGERED = "triggered"
    COOLDOWN = "cooldown"
    ERROR = "error"
    STOPPED = "stopped"


class EventStatus(str, Enum):
    SAVED = "saved"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(slots=True)
class EventRecord:
    id: int | None
    event_id: str
    triggered_at: str
    label: str
    video_path: str
    thumbnail_path: str
    pre_record_seconds: float
    post_record_seconds: float
    duration_seconds: float
    motion_score: float
    status: str
    error: str | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EngineSnapshot:
    state: str
    armed_requested: bool
    camera_id: int
    camera_ready: bool
    last_event_at: str | None
    last_error: str | None
    started_at: str
    recording: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
