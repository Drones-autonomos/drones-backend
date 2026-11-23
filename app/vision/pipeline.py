"""Pipeline de captura y preprocesamiento de frames con OpenCV."""

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np


@dataclass(slots=True)
class FramePacket:
    """Representa un frame capturado y metadatos básicos."""

    frame_id: int
    timestamp: datetime
    frame: np.ndarray
    source: str

    @property
    def height(self) -> int:
        return int(self.frame.shape[0])

    @property
    def width(self) -> int:
        return int(self.frame.shape[1])


class FramePipeline:
    """Captura, redimensiona, limita FPS y guarda evidencia visual desde fuentes OpenCV."""

    def __init__(
        self,
        source: str | int = 0,
        *,
        target_size: tuple[int, int] | None = (640, 640),
        max_fps: float = 10.0,
        evidence_dir: str | Path = "storage/frames",
    ) -> None:
        self.source = source
        self.target_size = target_size
        self.max_fps = max_fps
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Valida y redimensiona un frame BGR al tamaño configurado."""
        if frame is None or frame.size == 0:
            raise ValueError("Frame vacío o inválido")
        if self.target_size is None:
            return frame.copy()
        target_w, target_h = self.target_size
        if frame.shape[1] == target_w and frame.shape[0] == target_h:
            return frame.copy()
        return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

    def iter_frames(
        self,
        *,
        max_frames: int | None = None,
        throttle: bool = False,
    ) -> Iterator[FramePacket]:
        """Itera frames preprocesados desde un archivo, stream RTSP/HTTP o cámara."""
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            raise RuntimeError(f"No se pudo abrir la fuente de video: {self.source}")

        min_interval = (1.0 / self.max_fps) if self.max_fps > 0 else 0.0
        last_emit = 0.0
        frame_id = 0
        try:
            while max_frames is None or frame_id < max_frames:
                ok, raw = cap.read()
                if not ok:
                    break
                now = time.monotonic()
                if throttle and min_interval > 0 and (now - last_emit) < min_interval:
                    continue
                last_emit = now
                frame_id += 1
                yield FramePacket(
                    frame_id=frame_id,
                    timestamp=datetime.now(UTC).replace(tzinfo=None),
                    frame=self.preprocess(raw),
                    source=str(self.source),
                )
        finally:
            cap.release()

    def iter_from_arrays(self, frames: Iterator[np.ndarray] | list[np.ndarray]) -> Iterator[FramePacket]:
        """Itera frames desde arreglos en memoria (útil para pruebas o streams custom)."""
        for idx, raw in enumerate(frames, start=1):
            yield FramePacket(
                frame_id=idx,
                timestamp=datetime.now(UTC).replace(tzinfo=None),
                frame=self.preprocess(raw),
                source="memory",
            )

    @staticmethod
    def annotate(frame: np.ndarray, detections: list[dict]) -> np.ndarray:
        """Dibuja cajas delimitadoras y etiquetas sobre una copia del frame."""
        annotated = frame.copy()
        for det in detections:
            x1, y1, x2, y2 = (int(v) for v in det["bbox"])
            label = f"{det['tipo']} {det['confianza']:.2f}"
            color = (0, 0, 255) if det["tipo"] == "HUMO" else (0, 200, 0)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                annotated,
                label,
                (x1, max(16, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
                cv2.LINE_AA,
            )
        return annotated

    def save_evidence(self, frame: np.ndarray, prefix: str = "frame") -> str:
        """Guarda un frame anotado como JPEG y devuelve su ruta relativa."""
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{prefix}_{stamp}.jpg"
        output_path = self.evidence_dir / filename
        ok = cv2.imwrite(str(output_path), frame)
        if not ok:
            raise RuntimeError(f"No se pudo guardar la evidencia en {output_path}")
        return str(output_path)
