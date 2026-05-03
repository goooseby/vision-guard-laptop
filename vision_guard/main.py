from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

import webview

from vision_guard.app import Application
from vision_guard.bridge.api import BridgeApi
from vision_guard.desktop import SingleInstance, TrayController, set_start_on_login, startup_command

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Laptop Sentinel desktop app")
    parser.add_argument("--config", type=Path, help="Path to config.json")
    parser.add_argument("--debug", action="store_true", help="Enable pywebview debug mode")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    app = Application(project_root=project_root, config_path=args.config)
    try:
        set_start_on_login(
            enabled=app.config.desktop.start_on_login,
            command=startup_command(project_root, app.config_path),
        )
    except Exception:  # noqa: BLE001 - startup sync must not block the app
        LOGGER.exception("Failed to sync startup setting")

    window_holder: dict[str, webview.Window | None] = {"window": None}
    exit_requested = threading.Event()
    pending_show = threading.Event()

    def show_window() -> None:
        window = window_holder["window"]
        if window is None:
            pending_show.set()
            return
        try:
            window.show()
            window.restore()
        except Exception:  # noqa: BLE001 - tray and single-instance callbacks must be resilient
            LOGGER.exception("Failed to show main window")

    single_instance: SingleInstance | None = None
    if app.config.desktop.single_instance:
        single_instance = SingleInstance(
            port=app.config.desktop.single_instance_port,
            on_show=show_window,
        )
        if not single_instance.acquire():
            if single_instance.notify_existing():
                app.shutdown()
                return 0
            LOGGER.warning("Single instance port is busy; continuing without instance guard")

    api = BridgeApi(app)
    index_path = project_root / "vision_guard" / "ui" / "index.html"
    icon_path = project_root / "vision_guard" / "ui" / "assets" / "favicon.ico"

    def current_state() -> str:
        return app.engine.snapshot().state

    def request_exit() -> None:
        exit_requested.set()
        window = window_holder["window"]
        if window is not None:
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                LOGGER.exception("Failed to destroy main window")

    tray = TrayController(
        app_config=app.config,
        icon_path=icon_path,
        get_status=current_state,
        on_show=show_window,
        on_arm=lambda: app.engine.arm(),
        on_disarm=lambda: app.engine.disarm(),
        on_exit=request_exit,
    )

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
    window_holder["window"] = window
    if pending_show.is_set():
        show_window()

    def hide_window() -> None:
        try:
            window.hide()
            tray.update()
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed to hide main window")

    def on_closed(*_: object) -> None:
        app.shutdown()

    def on_closing(*_: object) -> bool | None:
        if app.config.desktop.close_to_tray and not exit_requested.is_set():
            threading.Timer(0.05, hide_window).start()
            return False
        return None

    def on_minimized(*_: object) -> None:
        if app.config.desktop.minimize_to_tray and not exit_requested.is_set():
            hide_window()

    window.events.closing += on_closing
    window.events.closed += on_closed
    window.events.minimized += on_minimized
    try:
        app.start()
        tray.start()
        webview.start(debug=args.debug or app.config.debug.debug_preview, icon=str(icon_path))
    finally:
        tray.stop()
        if single_instance is not None:
            single_instance.close()
        app.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
