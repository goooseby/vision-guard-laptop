from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pystray
from PIL import Image
from pystray import Menu, MenuItem

from vision_guard.config import AppConfig
from vision_guard.core.models import EngineState

LOGGER = logging.getLogger(__name__)
INSTANCE_MESSAGE = b"VISION_GUARD_SHOW\n"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_NAME = "Laptop Sentinel"


class SingleInstance:
    """Small localhost listener used to prevent duplicate monitor processes.

    A second process connects to the first one and sends a short wake-up message.
    The listener then asks the existing pywebview window to show itself.
    """

    def __init__(self, *, port: int, on_show: Callable[[], None]):
        self.port = port
        self.on_show = on_show
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def acquire(self) -> bool:
        """Bind the instance port and start listening for future launches."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows otherwise allows surprising duplicate binds with SO_REUSEADDR.
            server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            server.bind(("127.0.0.1", self.port))
            server.listen(3)
        except OSError:
            server.close()
            return False

        self._socket = server
        self._thread = threading.Thread(
            target=self._serve,
            name="vision-guard-single-instance",
            daemon=True,
        )
        self._thread.start()
        return True

    def notify_existing(self) -> bool:
        """Ask an already-running instance to reveal its window."""
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.6) as client:
                client.sendall(INSTANCE_MESSAGE)
            return True
        except OSError:
            return False

    def close(self) -> None:
        self._stop_event.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _serve(self) -> None:
        while not self._stop_event.is_set() and self._socket is not None:
            try:
                client, _ = self._socket.accept()
            except OSError:
                return
            with client:
                try:
                    data = client.recv(128)
                except OSError:
                    continue
            if data == INSTANCE_MESSAGE:
                try:
                    self.on_show()
                except Exception:  # noqa: BLE001 - listener must stay alive
                    LOGGER.exception("Failed to show existing window")


class TrayController:
    """Owns the system tray icon, menu callbacks, and status refresh thread."""

    def __init__(
        self,
        *,
        app_config: AppConfig,
        icon_path: Path,
        get_status: Callable[[], str],
        on_show: Callable[[], None],
        on_arm: Callable[[], None],
        on_disarm: Callable[[], None],
        on_exit: Callable[[], None],
    ):
        self.app_config = app_config
        self.icon_path = icon_path
        self.get_status = get_status
        self.on_show = on_show
        self.on_arm = on_arm
        self.on_disarm = on_disarm
        self.on_exit = on_exit
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None
        self._status_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Register the tray icon and menu on a background thread."""
        image = Image.open(self.icon_path)
        self._stop_event.clear()
        self._icon = pystray.Icon(
            "Laptop Sentinel",
            image,
            "Laptop Sentinel",
            self._menu(),
        )
        self._thread = threading.Thread(
            target=self._icon.run,
            name="vision-guard-tray",
            daemon=True,
        )
        self._thread.start()
        self._status_thread = threading.Thread(
            target=self._poll_status,
            name="vision-guard-tray-status",
            daemon=True,
        )
        self._status_thread.start()
        LOGGER.info("Tray icon started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._icon is not None:
            self._icon.stop()
            self._icon = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._status_thread is not None:
            self._status_thread.join(timeout=1)
            self._status_thread = None
        LOGGER.info("Tray icon stopped")

    def update(self) -> None:
        """Refresh tray title and menu enablement from the current engine state."""
        if self._icon is None:
            return
        self._icon.title = f"Laptop Sentinel - {state_text(self.get_status())}"
        self._icon.update_menu()

    def set_config(self, config: AppConfig) -> None:
        self.app_config = config
        self.update()

    def _menu(self) -> Menu:
        return Menu(
            MenuItem("打开主界面", self._show, default=True),
            MenuItem(lambda _: f"状态：{state_text(self.get_status())}", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("布防", self._arm, enabled=lambda _: self._can_arm()),
            MenuItem("撤防", self._disarm, enabled=lambda _: self._can_disarm()),
            Menu.SEPARATOR,
            MenuItem("退出 Laptop Sentinel", self._exit),
        )

    def _poll_status(self) -> None:
        while not self._stop_event.wait(3):
            self.update()

    def _show(self, *_: Any) -> None:
        self.on_show()

    def _arm(self, *_: Any) -> None:
        self.on_arm()
        self.update()

    def _disarm(self, *_: Any) -> None:
        self.on_disarm()
        self.update()

    def _exit(self, *_: Any) -> None:
        self.on_exit()

    def _can_arm(self) -> bool:
        return self.get_status() in {
            EngineState.DISARMED.value,
            EngineState.ERROR.value,
            EngineState.STOPPED.value,
        }

    def _can_disarm(self) -> bool:
        return self.get_status() not in {
            EngineState.DISARMED.value,
            EngineState.STOPPED.value,
        }


def state_text(state: str) -> str:
    return {
        EngineState.DISARMED.value: "已撤防",
        EngineState.ARMING.value: "正在布防",
        EngineState.ARMED.value: "布防中",
        EngineState.TRIGGERED.value: "已触发",
        EngineState.COOLDOWN.value: "冷却中",
        EngineState.ERROR.value: "需要处理",
        EngineState.STOPPED.value: "已停止",
    }.get(state, state)


def startup_command(project_root: Path, config_path: Path) -> str:
    """Build the command stored in Windows startup registration.

    Packaged builds can start the frozen executable directly. Development builds
    use `pythonw.exe` plus a small runner script so startup does not flash a
    console window.
    """
    if getattr(sys, "frozen", False):
        return quote_arg(Path(sys.executable))
    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    if pythonw.exists():
        executable = pythonw
    runner = project_root / "scripts" / "start_desktop.py"
    return " ".join(
        [
            quote_arg(executable),
            quote_arg(runner),
            "--config",
            quote_arg(config_path),
        ]
    )


def set_start_on_login(*, enabled: bool, command: str) -> None:
    """Create or remove the current-user Windows Run entry."""
    if sys.platform != "win32":
        return

    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, STARTUP_NAME)
            except FileNotFoundError:
                pass


def quote_arg(value: Path | str) -> str:
    return subprocess.list2cmdline([os.fspath(value)])
