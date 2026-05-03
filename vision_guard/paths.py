from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_config_path, user_data_path, user_log_path

APP_NAME = "Laptop Sentinel"
APP_AUTHOR = "Vision Guard"


@dataclass(frozen=True, slots=True)
class AppPaths:
    project_root: Path
    config_path: Path
    data_root: Path
    log_root: Path
    portable: bool = False

    @classmethod
    def resolve(cls, project_root: Path, config_path: Path | None = None) -> AppPaths:
        if config_path is not None:
            return cls(
                project_root=project_root,
                config_path=config_path,
                data_root=project_root,
                log_root=project_root,
                portable=True,
            )

        config_dir = user_config_path(APP_NAME, APP_AUTHOR)
        data_root = user_data_path(APP_NAME, APP_AUTHOR)
        log_root = user_log_path(APP_NAME, APP_AUTHOR)
        path = cls(
            project_root=project_root,
            config_path=config_dir / "config.json",
            data_root=data_root,
            log_root=log_root,
            portable=False,
        )
        path.prepare_desktop_config()
        return path

    def prepare_desktop_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.log_root.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            return

        legacy_config = self.project_root / "config.json"
        if legacy_config.exists():
            migrate_legacy_config(
                legacy_config=legacy_config,
                target_config=self.config_path,
                project_root=self.project_root,
            )


def migrate_legacy_config(*, legacy_config: Path, target_config: Path, project_root: Path) -> None:
    data = json.loads(legacy_config.read_text(encoding="utf-8"))
    paths = data.setdefault("paths", {})
    storage_path = paths.get("storage_path", "storage")
    legacy_storage = resolve_relative(project_root, storage_path)

    if legacy_storage.exists() and storage_path and not Path(storage_path).expanduser().is_absolute():
        paths["storage_path"] = str(legacy_storage)

    target_config.parent.mkdir(parents=True, exist_ok=True)
    target_config.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_relative(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return base / path


def runtime_locations(paths: AppPaths, config: Any) -> dict[str, Any]:
    return {
        "config_path": str(paths.config_path),
        "data_root": str(paths.data_root),
        "log_root": str(paths.log_root),
        "storage_path": str(config.storage_dir(paths.data_root)),
        "log_path": str(config.log_dir(paths.log_root)),
        "portable": paths.portable,
    }


def copy_example_config(project_root: Path, target_config: Path) -> None:
    target_config.parent.mkdir(parents=True, exist_ok=True)
    example = project_root / "config.example.json"
    if example.exists():
        shutil.copyfile(example, target_config)
