from __future__ import annotations

import base64
import logging
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from vision_guard.config import AppConfig
from vision_guard.core.models import EngineSnapshot, EngineState, EventRecord, EventStatus
from vision_guard.storage.database import EventDatabase

LOGGER = logging.getLogger(__name__)


class MonitorEngine:
    def __init__(self, *, config: AppConfig, database: EventDatabase, project_root: Path):
        self.config = config
        self.database = database
        self.project_root = project_root
        self.storage_dir = config.storage_dir(project_root)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._armed_requested = False
        self._state = EngineState.DISARMED
        self._camera_ready = False
        self._recording = False
        self._preview_active = False
        self._last_error: str | None = None
        self._last_event_at: str | None = None
        self._latest_frame: np.ndarray | None = None
        self._latest_frame_at: str | None = None
        self._last_motion_score = 0.0
        self._last_motion_score_ratio = 0.0
        self._last_motion_active = False
        self._last_motion_updated_at: str | None = None
        self._last_motion_roi: dict[str, float] = self._configured_roi()
        self._last_heatmap_boxes: list[dict[str, float]] = []
        self._started_at = datetime.now().astimezone().isoformat()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="vision-guard-monitor", daemon=True)
        self._thread.start()
        LOGGER.info("Monitor engine started")

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self._armed_requested = False
        if self._thread:
            self._thread.join(timeout=5)
        self._set_state(EngineState.STOPPED)
        LOGGER.info("Monitor engine stopped")

    def arm(self) -> dict[str, Any]:
        with self._lock:
            self._armed_requested = True
            self._last_error = None
            if self._state in {EngineState.DISARMED, EngineState.ERROR, EngineState.STOPPED}:
                self._state = EngineState.ARMING
        LOGGER.info("Arm requested")
        return self.snapshot().to_dict()

    def disarm(self) -> dict[str, Any]:
        with self._lock:
            self._armed_requested = False
            if self._state != EngineState.TRIGGERED:
                self._state = EngineState.DISARMED
        LOGGER.info("Disarm requested")
        return self.snapshot().to_dict()

    def snapshot(self) -> EngineSnapshot:
        with self._lock:
            return EngineSnapshot(
                state=self._state.value,
                armed_requested=self._armed_requested,
                camera_id=self.config.camera.camera_id,
                camera_ready=self._camera_ready,
                last_event_at=self._last_event_at,
                last_error=self._last_error,
                started_at=self._started_at,
                recording=self._recording,
                preview_available=self._latest_frame is not None,
                preview_active=self._preview_active,
                capture_fps=self.config.camera.capture_fps,
                motion_score=round(self._last_motion_score, 2),
                motion_score_ratio=round(self._last_motion_score_ratio, 3),
                motion_threshold=self.config.motion.motion_sensitivity,
                motion_active=self._last_motion_active,
                motion_updated_at=self._last_motion_updated_at,
                motion_roi=self._normalized_roi(),
                heatmap_boxes=list(self._last_heatmap_boxes) if self.config.motion.heatmap_enabled else [],
            )

    def set_preview_active(self, active: bool) -> dict[str, Any]:
        with self._lock:
            self._preview_active = active
            if not active:
                self._latest_frame = None
                self._latest_frame_at = None
        return self.snapshot().to_dict()

    def preview_frame(self, *, max_width: int = 960, jpeg_quality: int = 78) -> dict[str, Any]:
        with self._lock:
            preview_active = self._preview_active
            frame = None if self._latest_frame is None else self._latest_frame.copy()
            captured_at = self._latest_frame_at
            state = self._state.value
            camera_ready = self._camera_ready

        if not preview_active or frame is None:
            return {
                "available": False,
                "preview_active": preview_active,
                "state": state,
                "camera_ready": camera_ready,
                "captured_at": captured_at,
                "image": "",
                "motion": self._motion_payload(),
            }

        if max_width > 0 and frame.shape[1] > max_width:
            scale = max_width / frame.shape[1]
            frame = cv2.resize(frame, (max_width, int(frame.shape[0] * scale)))

        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), max(35, min(95, jpeg_quality))],
        )
        if not ok:
            return {
                "available": False,
                "preview_active": preview_active,
                "state": state,
                "camera_ready": camera_ready,
                "captured_at": captured_at,
                "image": "",
                "motion": self._motion_payload(),
            }

        return {
            "available": True,
            "preview_active": preview_active,
            "state": state,
            "camera_ready": camera_ready,
            "captured_at": captured_at,
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0]),
            "image": base64.b64encode(encoded.tobytes()).decode("ascii"),
            "motion": self._motion_payload(),
        }

    def _run(self) -> None:
        camera: cv2.VideoCapture | None = None
        previous_gray: np.ndarray | None = None
        pre_buffer: deque[np.ndarray] = self._new_pre_buffer()
        last_detect_at = 0.0

        while not self._stop_event.is_set():
            if not self._is_arm_requested():
                previous_gray = None
                pre_buffer.clear()
                camera = self._release_camera(camera)
                self._set_camera_ready(False)
                self._set_latest_frame(None)
                self._reset_motion_snapshot()
                self._set_state(EngineState.DISARMED)
                self._sleep(0.2)
                continue

            if camera is None or not camera.isOpened():
                camera = self._open_camera()
                previous_gray = None
                pre_buffer.clear()
                if camera is None:
                    self._sleep(1.5)
                    continue

            ok, frame = camera.read()
            if not ok or frame is None:
                self._set_error("摄像头读取失败，正在尝试恢复")
                camera = self._release_camera(camera)
                previous_gray = None
                pre_buffer.clear()
                self._sleep(1.0)
                continue

            self._remember_preview_frame(frame)

            if self.config.recording.pre_record_enabled:
                pre_buffer.append(frame.copy())

            now = time.monotonic()
            detect_interval = 1.0 / max(1, self.config.camera.detect_fps)
            if now - last_detect_at < detect_interval:
                self._sleep(self._capture_interval())
                continue
            last_detect_at = now

            current_gray = self._prepare_gray(frame)
            if previous_gray is None:
                previous_gray = current_gray
                self._set_state(EngineState.ARMED)
                self._sleep(self._capture_interval())
                continue

            motion = self._analyze_motion(previous_gray, current_gray)
            motion_score = motion["score"]
            previous_gray = current_gray
            self._set_motion_snapshot(motion)
            self._set_state(EngineState.ARMED)

            if motion_score >= self.config.motion.motion_sensitivity:
                LOGGER.info("Motion detected, score=%.2f", motion_score)
                self._record_event(camera, list(pre_buffer), frame, motion_score)
                pre_buffer.clear()
                previous_gray = None
                if self._is_arm_requested() and self.config.recording.cooldown_seconds > 0:
                    self._set_state(EngineState.COOLDOWN)
                    self._sleep_interruptible(self.config.recording.cooldown_seconds)

            if self.config.debug.debug_preview:
                cv2.imshow("Laptop Sentinel Debug", frame)
                cv2.waitKey(1)

            self._sleep(self._capture_interval())

        self._release_camera(camera)
        self._set_camera_ready(False)
        self._set_latest_frame(None)
        if self.config.debug.debug_preview:
            cv2.destroyAllWindows()

    def _open_camera(self) -> cv2.VideoCapture | None:
        self._set_state(EngineState.ARMING)
        camera_id = self.config.camera.camera_id
        backends = [cv2.CAP_DSHOW, 0] if sys.platform.startswith("win") else [0]

        for backend in backends:
            camera = cv2.VideoCapture(camera_id, backend) if backend else cv2.VideoCapture(camera_id)
            if camera.isOpened():
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera.frame_width)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera.frame_height)
                camera.set(cv2.CAP_PROP_FPS, self.config.camera.capture_fps)
                self._set_camera_ready(True)
                self._set_state(EngineState.ARMED)
                LOGGER.info("Camera %s opened", camera_id)
                return camera
            camera.release()

        self._set_camera_ready(False)
        self._set_error(f"摄像头 #{camera_id} 不可用或被其他程序占用")
        return None

    def _release_camera(self, camera: cv2.VideoCapture | None) -> None:
        if camera is not None:
            camera.release()
            LOGGER.info("Camera released")
        return None

    def _record_event(
        self,
        camera: cv2.VideoCapture,
        pre_frames: list[np.ndarray],
        trigger_frame: np.ndarray,
        motion_score: float,
    ) -> None:
        triggered_at = datetime.now().astimezone()
        event_id = triggered_at.strftime("EVENT_%Y%m%d_%H%M%S_%f")[:-3]
        self._set_state(EngineState.TRIGGERED)
        self._set_recording(True)

        video_path = self.storage_dir / f"{event_id}.mp4"
        thumbnail_path = self.storage_dir / f"{event_id}.jpg"
        tmp_video_path = self.storage_dir / f"{event_id}.part.mp4"
        tmp_thumbnail_path = self.storage_dir / f"{event_id}.part.jpg"

        try:
            result = self._write_event_files(
                camera=camera,
                pre_frames=pre_frames,
                trigger_frame=trigger_frame,
                video_path=video_path,
                thumbnail_path=thumbnail_path,
                tmp_video_path=tmp_video_path,
                tmp_thumbnail_path=tmp_thumbnail_path,
            )
            record = EventRecord(
                id=None,
                event_id=event_id,
                triggered_at=triggered_at.isoformat(),
                label="画面移动",
                video_path=self._relative(video_path),
                thumbnail_path=self._relative(thumbnail_path),
                pre_record_seconds=result["pre_record_seconds"],
                post_record_seconds=self.config.recording.record_duration,
                duration_seconds=result["duration_seconds"],
                motion_score=motion_score,
                status=EventStatus.SAVED.value,
                error=None,
                created_at=datetime.now().astimezone().isoformat(),
            )
            self.database.create_event(record)
            with self._lock:
                self._last_event_at = record.triggered_at
                self._last_error = None
            LOGGER.info("Event saved: %s", event_id)
        except Exception as exc:  # noqa: BLE001 - keep monitor alive after evidence failures
            LOGGER.exception("Failed to save event %s", event_id)
            tmp_video_path.unlink(missing_ok=True)
            tmp_thumbnail_path.unlink(missing_ok=True)
            self.database.mark_failed(
                event_id=event_id,
                triggered_at=triggered_at.isoformat(),
                label="画面移动",
                motion_score=motion_score,
                error=str(exc),
            )
            self._set_error(f"事件保存失败：{exc}")
        finally:
            self._set_recording(False)
            if not self._is_arm_requested():
                self._set_state(EngineState.DISARMED)

    def _write_event_files(
        self,
        *,
        camera: cv2.VideoCapture,
        pre_frames: list[np.ndarray],
        trigger_frame: np.ndarray,
        video_path: Path,
        thumbnail_path: Path,
        tmp_video_path: Path,
        tmp_thumbnail_path: Path,
    ) -> dict[str, float]:
        height, width = trigger_frame.shape[:2]
        writer = cv2.VideoWriter(
            str(tmp_video_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            float(self.config.camera.capture_fps),
            (width, height),
        )
        if not writer.isOpened():
            raise RuntimeError("视频编码器初始化失败")

        written_frames = 0
        try:
            for frame in pre_frames:
                writer.write(self._resize_if_needed(frame, width, height))
                written_frames += 1

            end_at = time.monotonic() + self.config.recording.record_duration
            while time.monotonic() < end_at and not self._stop_event.is_set():
                ok, frame = camera.read()
                if not ok or frame is None:
                    LOGGER.warning("Camera read failed during recording")
                    break
                self._remember_preview_frame(frame)
                writer.write(self._resize_if_needed(frame, width, height))
                written_frames += 1
                self._sleep(self._capture_interval())
        finally:
            writer.release()

        if written_frames <= 0:
            raise RuntimeError("录像没有写入任何帧")

        if not cv2.imwrite(str(tmp_thumbnail_path), trigger_frame):
            raise RuntimeError("缩略图写入失败")

        tmp_video_path.replace(video_path)
        tmp_thumbnail_path.replace(thumbnail_path)

        return {
            "duration_seconds": round(written_frames / max(1, self.config.camera.capture_fps), 2),
            "pre_record_seconds": round(len(pre_frames) / max(1, self.config.camera.capture_fps), 2),
        }

    def _new_pre_buffer(self) -> deque[np.ndarray]:
        maxlen = max(
            1,
            self.config.recording.pre_record_seconds * self.config.camera.capture_fps,
        )
        return deque(maxlen=maxlen)

    def _prepare_gray(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(gray, (21, 21), 0)

    def _analyze_motion(self, previous_gray: np.ndarray, current_gray: np.ndarray) -> dict[str, Any]:
        height, width = current_gray.shape[:2]
        left, top, roi_width, roi_height = self._roi_rect(width, height)
        previous_roi = previous_gray[top : top + roi_height, left : left + roi_width]
        current_roi = current_gray[top : top + roi_height, left : left + roi_width]

        delta = cv2.absdiff(previous_roi, current_roi)
        threshold = cv2.threshold(
            delta,
            self.config.motion.threshold_value,
            255,
            cv2.THRESH_BINARY,
        )[1]
        threshold = cv2.dilate(threshold, None, iterations=2)
        contours, _ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        total = 0.0
        boxes: list[dict[str, float]] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area >= self.config.motion.min_contour_area:
                total += area
                x, y, box_width, box_height = cv2.boundingRect(contour)
                boxes.append(
                    {
                        "x": round((left + x) / width, 4),
                        "y": round((top + y) / height, 4),
                        "width": round(box_width / width, 4),
                        "height": round(box_height / height, 4),
                        "score": round(float(area), 2),
                    }
                )

        boxes.sort(key=lambda item: item["score"], reverse=True)
        threshold_score = max(1, self.config.motion.motion_sensitivity)
        return {
            "score": float(total),
            "ratio": min(1.0, float(total) / threshold_score),
            "active": total >= self.config.motion.motion_sensitivity,
            "roi": self._normalized_roi(),
            "boxes": boxes[:8] if self.config.motion.heatmap_enabled else [],
        }

    def _roi_rect(self, width: int, height: int) -> tuple[int, int, int, int]:
        roi = self._normalized_roi()
        left = min(width - 1, max(0, int(round(roi["x"] * width))))
        top = min(height - 1, max(0, int(round(roi["y"] * height))))
        right = min(width, max(left + 1, int(round((roi["x"] + roi["width"]) * width))))
        bottom = min(height, max(top + 1, int(round((roi["y"] + roi["height"]) * height))))
        return left, top, right - left, bottom - top

    def _normalized_roi(self) -> dict[str, float]:
        if not self.config.motion.roi_enabled:
            return {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
        return self._configured_roi()

    def _configured_roi(self) -> dict[str, float]:
        motion = self.config.motion
        return {
            "x": round(float(motion.roi_x), 4),
            "y": round(float(motion.roi_y), 4),
            "width": round(float(motion.roi_width), 4),
            "height": round(float(motion.roi_height), 4),
        }

    def _resize_if_needed(self, frame: np.ndarray, width: int, height: int) -> np.ndarray:
        if frame.shape[1] == width and frame.shape[0] == height:
            return frame
        return cv2.resize(frame, (width, height))

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.project_root).as_posix()
        except ValueError:
            return path.as_posix()

    def _capture_interval(self) -> float:
        return 1.0 / max(1, self.config.camera.capture_fps)

    def _is_arm_requested(self) -> bool:
        with self._lock:
            return self._armed_requested

    def _set_state(self, state: EngineState) -> None:
        with self._lock:
            if self._state != state:
                LOGGER.info("Engine state -> %s", state.value)
            self._state = state

    def _set_camera_ready(self, ready: bool) -> None:
        with self._lock:
            self._camera_ready = ready

    def _set_latest_frame(self, frame: np.ndarray | None) -> None:
        with self._lock:
            self._latest_frame = None if frame is None else frame.copy()
            self._latest_frame_at = None if frame is None else datetime.now().astimezone().isoformat()

    def _remember_preview_frame(self, frame: np.ndarray) -> None:
        with self._lock:
            active = self._preview_active
        if active:
            self._set_latest_frame(frame)

    def _set_recording(self, recording: bool) -> None:
        with self._lock:
            self._recording = recording

    def _set_motion_snapshot(self, motion: dict[str, Any]) -> None:
        with self._lock:
            self._last_motion_score = float(motion["score"])
            self._last_motion_score_ratio = float(motion["ratio"])
            self._last_motion_active = bool(motion["active"])
            self._last_motion_updated_at = datetime.now().astimezone().isoformat()
            self._last_motion_roi = dict(motion["roi"])
            self._last_heatmap_boxes = list(motion["boxes"])

    def _reset_motion_snapshot(self) -> None:
        with self._lock:
            self._last_motion_score = 0.0
            self._last_motion_score_ratio = 0.0
            self._last_motion_active = False
            self._last_motion_updated_at = None
            self._last_motion_roi = self._normalized_roi()
            self._last_heatmap_boxes = []

    def _motion_payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "score": round(self._last_motion_score, 2),
                "ratio": round(self._last_motion_score_ratio, 3),
                "threshold": self.config.motion.motion_sensitivity,
                "active": self._last_motion_active,
                "updated_at": self._last_motion_updated_at,
                "roi": self._normalized_roi(),
                "boxes": list(self._last_heatmap_boxes) if self.config.motion.heatmap_enabled else [],
            }

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._state = EngineState.ERROR
            self._last_error = message
        LOGGER.error(message)

    def _sleep(self, seconds: float) -> None:
        self._stop_event.wait(max(0.0, seconds))

    def _sleep_interruptible(self, seconds: int) -> None:
        end_at = time.monotonic() + seconds
        while time.monotonic() < end_at and not self._stop_event.is_set():
            if not self._is_arm_requested():
                return
            self._sleep(0.2)
