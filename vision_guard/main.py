from __future__ import annotations

import argparse
from pathlib import Path

import webview

from vision_guard.app import Application
from vision_guard.bridge.api import BridgeApi


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Laptop Sentinel desktop app")
    parser.add_argument("--config", type=Path, help="Path to config.json")
    parser.add_argument("--debug", action="store_true", help="Enable pywebview debug mode")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    app = Application(project_root=project_root, config_path=args.config)
    api = BridgeApi(app)
    index_path = project_root / "vision_guard" / "ui" / "index.html"

    window = webview.create_window(
        "Laptop Sentinel",
        url=index_path.as_uri(),
        js_api=api,
        width=app.config.ui.window_width,
        height=app.config.ui.window_height,
        min_size=(900, 620),
        frameless=app.config.ui.frameless,
        easy_drag=app.config.ui.frameless,
    )

    def on_closed(*_: object) -> None:
        app.shutdown()

    window.events.closed += on_closed
    try:
        app.start()
        webview.start(debug=args.debug or app.config.debug.debug_preview)
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
