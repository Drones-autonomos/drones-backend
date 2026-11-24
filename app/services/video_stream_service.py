"""Servicio de streaming de video en vivo con buffer de frames, reconexión y perfiles de calidad."""

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Condition, RLock

import cv2
import numpy as np

from app.core.config import settings

QUALITY_PROFILES: dict[str, tuple[str, int, int]] = {
    "hd-30": ("1280x720", 30, 70),
    "fhd-60": ("1920x1080", 60, 82),
    "4k-30": ("3840x2160", 30, 90),
}


@dataclass(slots=True)
class LiveFrame:
    sequence: int
    timestamp: datetime
    jpeg_bytes: bytes
    width: int
    height: int


class VideoStreamService:
    """Administra el flujo de frames en vivo desde la cámara simulada o RTSP."""

    def __init__(
        self,
        *,
        fps: int | None = None,
        jpeg_quality: int | None = None,
    ) -> None:
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._latest: LiveFrame | None = None
        self._sequence = 0
        self._reconnects = 0
        self._online = False
        self.fps = fps or settings.VIDEO_STREAM_FPS
        self.jpeg_quality = jpeg_quality or settings.VIDEO_JPEG_QUALITY
        self.resolution = "1280x720"
        self.quality_profile = "fhd-60"

    def apply_quality_profile(self, profile_id: str) -> dict:
        """Aplica dinámicamente un perfil de calidad de transmisión (hd-30, fhd-60, 4k-30)."""
        spec = QUALITY_PROFILES.get(str(profile_id))
        with self._lock:
            if spec is not None:
                resolution, fps, jpeg_quality = spec
                self.quality_profile = str(profile_id)
                if not self._online:
                    self.resolution = resolution
                self.fps = fps
                self.jpeg_quality = jpeg_quality
            return self.get_status()

    def publish_jpeg(self, jpeg_bytes: bytes, *, width: int = 1280, height: int = 720) -> LiveFrame:
        if not jpeg_bytes:
            raise ValueError("Frame JPEG vacío")
        with self._condition:
            if not self._online and self._sequence > 0:
                self._reconnects += 1
            self._sequence += 1
            self._online = True
            self.resolution = f"{width}x{height}"
            frame = LiveFrame(
                sequence=self._sequence,
                timestamp=datetime.now(UTC),
                jpeg_bytes=jpeg_bytes,
                width=width,
                height=height,
            )
            self._latest = frame
            self._condition.notify_all()
            return frame

    def publish_ndarray(self, frame: np.ndarray) -> LiveFrame:
        if frame is None or frame.size == 0:
            raise ValueError("Frame inválido")
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(self.jpeg_quality)],
        )
        if not ok:
            raise RuntimeError("No se pudo codificar el frame en JPEG")
        height, width = frame.shape[:2]
        return self.publish_jpeg(encoded.tobytes(), width=width, height=height)

    def mark_offline(self) -> None:
        with self._condition:
            self._online = False
            self._condition.notify_all()

    def get_latest(self) -> LiveFrame | None:
        with self._lock:
            return self._latest

    def get_status(self) -> dict:
        with self._lock:
            return {
                "stream_url": settings.VIDEO_STREAM_URL,
                "protocolo": settings.VIDEO_STREAM_PROTOCOL,
                "estado_camara": "ONLINE" if self._online else "STANDBY",
                "resolucion": self.resolution,
                "fps": self.fps,
                "calidad_perfil": self.quality_profile,
                "frames_publicados": self._sequence,
                "reconexiones": self._reconnects,
                "ultimo_frame_at": self._latest.timestamp.isoformat() if self._latest else None,
            }

    def iter_mjpeg(self, *, max_frames: int | None = None, timeout_s: float = 2.0) -> Iterator[bytes]:
        """Genera partes multipart MJPEG esperando nuevos frames sin bloquear indefinidamente."""
        last_seq = 0
        emitted = 0
        interval = 1.0 / max(1, self.fps)
        while max_frames is None or emitted < max_frames:
            with self._condition:
                if self._latest is None or self._latest.sequence == last_seq:
                    self._condition.wait(timeout=timeout_s)
                frame = self._latest
                if frame is None:
                    break
                last_seq = frame.sequence
                payload = frame.jpeg_bytes

            emitted += 1
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
                + payload
                + b"\r\n"
            )
            if max_frames is None or emitted < max_frames:
                time.sleep(interval)


video_stream_service = VideoStreamService()
