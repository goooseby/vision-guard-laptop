from __future__ import annotations

import base64
import logging
import os
import platform
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vision_guard.app import Application
from vision_guard.config import AppConfig

LOGGER = logging.getLogger(__name__)


class BridgeApi:
    def __init__(self, app: Application):
        self.app = app

    def get_status(self) -> dict[str, Any]:
        return {"ok": True, "status": self.app.engine.snapshot().to_dict()}

    def get_preview_frame(self) -> dict[str, Any]:
        frame = self.app.engine.preview_frame(max_width=960, jpeg_quality=78)
        if frame.get("image"):
            frame["image"] = f"data:image/jpeg;base64,{frame['image']}"
        return {"ok": True, "frame": frame}

    def set_preview_active(self, active: bool) -> dict[str, Any]:
        return {"ok": True, "status": self.app.engine.set_preview_active(bool(active))}

    def arm(self) -> dict[str, Any]:
        return {"ok": True, "status": self.app.engine.arm()}

    def disarm(self) -> dict[str, Any]:
        return {"ok": True, "status": self.app.engine.disarm()}

    def list_events(self) -> dict[str, Any]:
        return self.list_events_filtered({})

    def list_events_filtered(self, filters: dict[str, Any]) -> dict[str, Any]:
        events = []
        for payload in self.app.events.list_events(filters):
            thumbnail_path = self._resolve(payload.get("thumbnail_path", ""))
            payload["thumbnail_data_url"] = self._thumbnail_data_url(thumbnail_path)
            events.append(payload)
        return {"ok": True, "events": events, "stats": self.app.events.stats()}

    def get_storage_stats(self) -> dict[str, Any]:
        return {"ok": True, "stats": self.app.events.stats()}

    def delete_events(self, event_ids: list[str]) -> dict[str, Any]:
        result = self.app.events.delete_events([str(event_id) for event_id in event_ids])
        return {"ok": True, "result": result.to_dict(), "stats": self.app.events.stats()}

    def cleanup_events(self, mode: str = "configured") -> dict[str, Any]:
        return {"ok": True, **self.app.events.cleanup(mode=mode)}

    def open_video(self, event_id: str) -> dict[str, Any]:
        event = self.app.database.get_event(event_id)
        if event is None:
            return {"ok": False, "error": "事件不存在"}
        video_path = self._resolve(event.video_path)
        if not video_path.exists():
            return {"ok": False, "error": "录像文件不存在或已被移动"}
        try:
            open_with_default_player(video_path)
        except Exception as exc:  # noqa: BLE001 - return actionable UI error
            LOGGER.exception("Failed to open video %s", video_path)
            return {"ok": False, "error": f"无法打开录像：{exc}"}
        return {"ok": True}

    def get_config(self) -> dict[str, Any]:
        return {"ok": True, "config": self.app.config.model_dump()}

    def save_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = deepcopy(self.app.config.model_dump())
        deep_update(current, patch)
        try:
            config = AppConfig.model_validate(current)
        except ValidationError as exc:
            return {"ok": False, "error": readable_validation_error(exc)}
        self.app.save_config(config)
        return {"ok": True, "config": config.model_dump(), "status": self.app.engine.snapshot().to_dict()}

    def reveal_storage(self) -> dict[str, Any]:
        path = self.app.config.storage_dir(self.app.project_root)
        path.mkdir(parents=True, exist_ok=True)
        try:
            open_with_default_player(path)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"无法打开存储目录：{exc}"}
        return {"ok": True}

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.app.project_root / path

    def _thumbnail_data_url(self, path: Path) -> str:
        if not path.exists() or not path.is_file():
            return ""
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"


def open_with_default_player(path: Path) -> None:
    system = platform.system().lower()
    if system == "windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif system == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = value


def readable_validation_error(exc: ValidationError) -> str:
    first = exc.errors()[0]
    loc = ".".join(str(part) for part in first.get("loc", []))
    return f"{loc}: {first.get('msg', '配置无效')}"
