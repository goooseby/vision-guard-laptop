from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CameraConfig(BaseModel):
    camera_id: int = 0
    capture_fps: int = Field(default=10, ge=1, le=60)
    detect_fps: int = Field(default=5, ge=1, le=30)
    frame_width: int = Field(default=640, ge=160, le=3840)
    frame_height: int = Field(default=480, ge=120, le=2160)

    @field_validator("detect_fps")
    @classmethod
    def detect_fps_must_not_exceed_capture(cls, value: int, info: Any) -> int:
        capture_fps = info.data.get("capture_fps")
        if capture_fps and value > capture_fps:
            return capture_fps
        return value


class MotionConfig(BaseModel):
    motion_sensitivity: int = Field(default=2500, ge=1)
    min_contour_area: int = Field(default=600, ge=1)
    threshold_value: int = Field(default=25, ge=1, le=255)


class RecordingConfig(BaseModel):
    record_duration: int = Field(default=10, ge=1, le=300)
    pre_record_enabled: bool = True
    pre_record_seconds: int = Field(default=3, ge=0, le=30)
    cooldown_seconds: int = Field(default=15, ge=0, le=600)


class PathConfig(BaseModel):
    storage_path: str = "storage"
    log_path: str = "logs"


class UiConfig(BaseModel):
    window_width: int = Field(default=1180, ge=900, le=2400)
    window_height: int = Field(default=760, ge=620, le=1600)
    frameless: bool = False
    theme: str = "dark"


class DebugConfig(BaseModel):
    debug_preview: bool = False
    log_level: str = "INFO"


class AppConfig(BaseModel):
    camera: CameraConfig = Field(default_factory=CameraConfig)
    motion: MotionConfig = Field(default_factory=MotionConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    paths: PathConfig = Field(default_factory=PathConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)

    @classmethod
    def load(cls, project_root: Path, config_path: Path | None = None) -> AppConfig:
        path = config_path or project_root / "config.json"
        if not path.exists():
            example = project_root / "config.example.json"
            if example.exists():
                shutil.copyfile(example, path)
            else:
                path.write_text(
                    json.dumps(cls().model_dump(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.model_dump(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def storage_dir(self, project_root: Path) -> Path:
        return resolve_user_path(project_root, self.paths.storage_path)

    def log_dir(self, project_root: Path) -> Path:
        return resolve_user_path(project_root, self.paths.log_path)


def resolve_user_path(project_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return project_root / path
