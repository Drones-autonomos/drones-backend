"""Pipeline de captura, privacidad estudiantil (difuminado facial) y preprocesamiento OpenCV."""

import hashlib
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
    """Captura, anonimiza rostros, redimensiona, limita FPS y guarda evidencia visual."""

    _face_cascade: cv2.CascadeClassifier | None = None
    _cascade_loaded: bool = False

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

    @classmethod
    def _get_face_cascade(cls) -> cv2.CascadeClassifier | None:
        if not cls._cascade_loaded:
            cls._cascade_loaded = True
            haar_dir = getattr(cv2.data, "haarcascades", "")
            xml_path = Path(haar_dir) / "haarcascade_frontalface_default.xml"
            if xml_path.exists():
                cascade = cv2.CascadeClassifier(str(xml_path))
                if not cascade.empty():
                    cls._face_cascade = cascade
        return cls._face_cascade

    @classmethod
    def blur_faces(
        cls,
        frame: np.ndarray,
        *,
        blur_kernel: tuple[int, int] = (35, 35),
        extra_boxes: list[tuple[int, int, int, int]] | None = None,
    ) -> np.ndarray:
        """Difumina rostros detectados en áreas abiertas (cumplimiento de privacidad UAQ)."""
        if frame is None or frame.size == 0:
            raise ValueError("Frame vacío o inválido")

        output = frame.copy()
        height, width = output.shape[:2]
        kx = max(3, int(blur_kernel[0]) | 1)
        ky = max(3, int(blur_kernel[1]) | 1)

        boxes: list[tuple[int, int, int, int]] = []
        cascade = cls._get_face_cascade()
        if cascade is not None:
            gray = cv2.cvtColor(output, cv2.COLOR_BGR2GRAY)
            detected = cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=4,
                minSize=(24, 24),
            )
            for x, y, w, h in detected:
                boxes.append((int(x), int(y), int(x + w), int(y + h)))

        if extra_boxes:
            boxes.extend(extra_boxes)

        for x1, y1, x2, y2 in boxes:
            cx1 = max(0, min(width, int(x1)))
            cy1 = max(0, min(height, int(y1)))
            cx2 = max(0, min(width, int(x2)))
            cy2 = max(0, min(height, int(y2)))
            if cx2 > cx1 and cy2 > cy1:
                roi = output[cy1:cy2, cx1:cx2]
                output[cy1:cy2, cx1:cx2] = cv2.GaussianBlur(roi, (kx, ky), 0)

        return output

    def preprocess(self, frame: np.ndarray, *, apply_face_blur: bool = False) -> np.ndarray:
        """Valida, opcionalmente anonimiza rostros y redimensiona un frame BGR."""
        if frame is None or frame.size == 0:
            raise ValueError("Frame vacío o inválido")
        working = self.blur_faces(frame) if apply_face_blur else frame.copy()
        if self.target_size is None:
            return working
        target_w, target_h = self.target_size
        if working.shape[1] == target_w and working.shape[0] == target_h:
            return working
        return cv2.resize(working, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

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

    def save_evidence(
        self,
        frame: np.ndarray,
        prefix: str = "frame",
        *,
        apply_face_blur: bool = False,
    ) -> str:
        """Guarda un frame anotado como JPEG y devuelve su ruta relativa."""
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{prefix}_{stamp}.jpg"
        output_path = self.evidence_dir / filename
        to_write = self.blur_faces(frame) if apply_face_blur else frame
        ok = cv2.imwrite(str(output_path), to_write)
        if not ok:
            raise RuntimeError(f"No se pudo guardar la evidencia en {output_path}")
        return str(output_path)

    def save_evidence_with_hash(
        self,
        frame: np.ndarray,
        prefix: str = "frame",
        *,
        apply_face_blur: bool = True,
    ) -> tuple[str, str]:
        """Guarda evidencia aplicando privacidad facial opcional y retorna (ruta, sha256)."""
        path_str = self.save_evidence(frame, prefix=prefix, apply_face_blur=apply_face_blur)
        digest = hashlib.sha256(Path(path_str).read_bytes()).hexdigest()
        return path_str, digest
