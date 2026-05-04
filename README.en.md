# Laptop Sentinel / Vision Guard

[中文](README.md) | English

## Overview

Laptop Sentinel is a local sentinel system built around a laptop camera. It uses Python, OpenCV, and pywebview, with the goal of becoming a reliable desktop application rather than a temporary script.

## Current Capabilities

- Standalone desktop window with system tray support, close/minimize-to-tray behavior, and single-instance protection.
- HTML/CSS/JavaScript frontend with a Python/OpenCV backend.
- Armed, disarmed, triggered, and cooldown state management.
- Low-FPS motion detection with ROI support, motion score, and heat overlay.
- In-memory pre-recording before a trigger and local recording after a trigger.
- MP4 videos, JPG thumbnails, and a SQLite event index.
- Event management with time filters, single/bulk delete, retention cleanup, and storage statistics.
- Settings for themes, desktop behavior, start-on-login, storage path, and runtime parameters.

Remote webhook alerts are intentionally deferred. The current priority is local usability and desktop reliability.

## Documentation

- [需求说明书.md](需求说明书.md): MVP scope, state model, and acceptance criteria.
- [docs/技术方案.md](docs/技术方案.md): Architecture, data flow, and technical decisions.
- [docs/环境准备.md](docs/环境准备.md): Development environment and dependency setup.

## Environment

Use the prepared conda environment:

```powershell
conda activate vision-guard
```

Install runtime dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install development and test dependencies:

```powershell
python -m pip install -r requirements-dev.txt
```

## Run

Run in development mode:

```powershell
python -m vision_guard
```

If VSCode is not using the `vision-guard` interpreter, use:

```powershell
.\scripts\start.ps1
```

Or specify the interpreter explicitly:

```powershell
$env:VISION_GUARD_PYTHON = "D:\pythonDev\Anaconda\envs\vision-guard\python.exe"
.\scripts\start.ps1
```

Enable pywebview debug mode:

```powershell
python -m vision_guard --debug
```

## Runtime Data

Desktop mode uses system user directories by default:

- Config: `AppData/Local/Vision Guard/Laptop Sentinel/config.json`
- Data: `AppData/Local/Vision Guard/Laptop Sentinel/`
- Logs: `AppData/Local/Vision Guard/Laptop Sentinel/Logs/`

If an older `config.json` exists in the project root, the first desktop-mode launch migrates it. If the old `storage/` folder already contains events, the migrated storage path keeps pointing to that folder so historical events remain visible.

## Usage Notes

The live preview is off by default. When enabled, it reads the latest frame from the backend capture engine without opening a second camera instance. Rendering stops when the dashboard is inactive or the window is hidden.

The preview shows motion score, ROI bounds, and heat boxes. You can drag on the preview to select a detection region, or adjust ROI values precisely in settings.

The Events view manages recorded evidence. Deleting an event removes its database row, video, and thumbnail. Changing the storage path only affects future events and does not migrate existing recordings.

Desktop mode enables close-to-tray, minimize-to-tray, and single-instance behavior by default. Use the tray menu item "退出 Laptop Sentinel" to really quit the app. Start-on-login is off by default and must be enabled by the user.

## Packaging

The first packaging target uses PyInstaller `onedir` + `windowed`. This is stable, easy to inspect, and suitable for early product validation.

Example command:

```powershell
python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name "Laptop Sentinel" `
  --icon "vision_guard\ui\assets\favicon.ico" `
  --add-data "vision_guard\ui;vision_guard\ui" `
  --add-data "config.example.json;." `
  scripts\start_desktop.py
```

Output location:

```text
dist\Laptop Sentinel\Laptop Sentinel.exe
```

## Verification

```powershell
python -m compileall vision_guard tests scripts
python -m ruff check vision_guard tests scripts
python -m pytest
node --check vision_guard\ui\app.js
```

## Safety Boundary

This system is only intended for devices and environments authorized by the user. It must not bypass operating-system camera permissions, camera indicator behavior, or user security policies.
