from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from vision_guard.config import AppConfig
from vision_guard.core.engine import MonitorEngine
from vision_guard.core.events import EventService
from vision_guard.paths import AppPaths
from vision_guard.storage.database import EventDatabase


class Application:
    """Composes configuration, storage, event services, and the monitor engine."""

    def __init__(self, project_root: Path, config_path: Path | None = None):
        self.project_root = project_root
        self.paths = AppPaths.resolve(project_root, config_path)
        self.runtime_root = self.paths.data_root
        self.log_root = self.paths.log_root
        self.config_path = self.paths.config_path
        self.config = AppConfig.load(project_root, self.config_path)
        self._setup_directories()
        self._setup_logging()

        self.database = EventDatabase(self.config.storage_dir(self.runtime_root) / "events.sqlite3")
        self.events = EventService(
            database=self.database,
            project_root=self.runtime_root,
            config=self.config,
        )
        self.engine = MonitorEngine(
            config=self.config,
            database=self.database,
            project_root=self.runtime_root,
        )
        self._shutdown = False

    def start(self) -> None:
        if self.config.retention.cleanup_on_start:
            self.events.cleanup(mode="configured")
        self.engine.start()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self.engine.stop()
        self.database.close()

    def save_config(self, config: AppConfig) -> None:
        """Persist config and refresh services that cache runtime paths/settings."""
        self.config = config
        self.engine.config = config
        self.engine.storage_dir = config.storage_dir(self.runtime_root)
        self.engine.storage_dir.mkdir(parents=True, exist_ok=True)
        self.events.set_config(config)
        config.save(self.config_path)

    def _setup_directories(self) -> None:
        self.config.storage_dir(self.runtime_root).mkdir(parents=True, exist_ok=True)
        self.config.log_dir(self.log_root).mkdir(parents=True, exist_ok=True)

    def _setup_logging(self) -> None:
        level = getattr(logging, self.config.debug.log_level.upper(), logging.INFO)
        root = logging.getLogger()
        root.setLevel(level)
        root.handlers.clear()

        formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        console.setLevel(level)
        root.addHandler(console)

        file_handler = RotatingFileHandler(
            self.config.log_dir(self.log_root) / "vision_guard.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)
