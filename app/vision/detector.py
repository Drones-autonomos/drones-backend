"""Detectores de personas (YOLOv8n ONNX) y humo (OpenCV/ONNX) para el módulo de visión."""

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(slots=True)
class VisionDetection:
    """Resultado normalizado de una detección sobre un frame."""

    tipo: str  # "PERSONA" | "HUMO"
    confianza: float
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)

    def to_dict(self) -> dict:
        return {
            "tipo": self.tipo,
            "confianza": float(self.confianza),
            "bbox": self.bbox,
        }


class PersonDetector:
    """Detector de personas usando YOLOv8n en formato ONNX mediante OpenCV DNN."""

    def __init__(
        self,
        model_path: str | Path = "models/yolov8n.onnx",
        *,
        metadata_path: str | Path | None = "models/person-model.json",
        confidence_threshold: float = 0.45,
        nms_threshold: float = 0.45,
        input_size: int = 640,
        target_class_id: int = 0,
    ) -> None:
        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.input_size = input_size
        self.target_class_id = target_class_id
        self.label = "PERSONA"

        if metadata_path and Path(metadata_path).exists():
            meta = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
            if isinstance(meta, list) and meta:
                entry = meta[0]
                self.input_size = int(entry.get("input_size", self.input_size))
                labels = entry.get("labels", {})
                self.label = str(labels.get(str(self.target_class_id), self.label)).upper()

        self._net = None

    def _ensure_loaded(self) -> None:
        if self._net is None:
            if not self.model_path.exists():
                raise FileNotFoundError(f"Modelo ONNX de personas no encontrado: {self.model_path}")
            self._net = cv2.dnn.readNetFromONNX(str(self.model_path))

    @property
    def is_available(self) -> bool:
        return self.model_path.exists()

    def parse_yolo_output(
        self,
        output: np.ndarray,
        frame_width: int,
        frame_height: int,
    ) -> list[VisionDetection]:
        """Decodifica tensores de salida YOLOv8 `(1, 84, N)` o `(N, 84)` con NMS."""
        if output.ndim == 3:
            preds = output[0].T
        elif output.ndim == 2:
            preds = output if output.shape[1] > 4 + self.target_class_id else output.T
        else:
            return []

        class_col = 4 + self.target_class_id
        if preds.shape[1] <= class_col:
            return []

        scores = preds[:, class_col]
        mask = scores >= self.confidence_threshold
        if not np.any(mask):
            return []

        filtered = preds[mask]
        filtered_scores = scores[mask]

        scale_x = frame_width / float(self.input_size)
        scale_y = frame_height / float(self.input_size)

        boxes: list[list[int]] = []
        confidences: list[float] = []
        for row, score in zip(filtered, filtered_scores, strict=True):
            cx, cy, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            x1 = max(0, int((cx - w / 2.0) * scale_x))
            y1 = max(0, int((cy - h / 2.0) * scale_y))
            bw = max(1, int(w * scale_x))
            bh = max(1, int(h * scale_y))
            boxes.append([x1, y1, bw, bh])
            confidences.append(float(score))

        indices = cv2.dnn.NMSBoxes(
            boxes,
            confidences,
            self.confidence_threshold,
            self.nms_threshold,
        )
        if len(indices) == 0:
            return []

        results: list[VisionDetection] = []
        for idx in np.array(indices).flatten():
            x, y, bw, bh = boxes[int(idx)]
            x2 = min(frame_width, x + bw)
            y2 = min(frame_height, y + bh)
            results.append(
                VisionDetection(
                    tipo=self.label,
                    confianza=min(1.0, confidences[int(idx)]),
                    bbox=(x, y, x2, y2),
                )
            )
        return results

    def detect(self, frame: np.ndarray) -> list[VisionDetection]:
        """Ejecuta inferencia de personas sobre un frame BGR."""
        if frame is None or frame.size == 0:
            return []
        self._ensure_loaded()
        blob = cv2.dnn.blobFromImage(
            frame,
            scalefactor=1.0 / 255.0,
            size=(self.input_size, self.input_size),
            swapRB=True,
            crop=False,
        )
        self._net.setInput(blob)
        output = self._net.forward()
        return self.parse_yolo_output(output, frame.shape[1], frame.shape[0])


class SmokeDetector:
    """Detector de humo mediante análisis cromático HSV, difusión espacial y movimiento opcional."""

    def __init__(
        self,
        *,
        confidence_threshold: float = 0.65,
        min_area_ratio: float = 0.015,
        max_saturation: int = 55,
        min_value: int = 125,
        max_value: int = 245,
        model_path: str | Path | None = None,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.min_area_ratio = min_area_ratio
        self.max_saturation = max_saturation
        self.min_value = min_value
        self.max_value = max_value
        self.model_path = Path(model_path) if model_path else None
        self._prev_gray: np.ndarray | None = None

    def reset(self) -> None:
        self._prev_gray = None

    def detect(self, frame: np.ndarray, *, use_motion: bool = False) -> list[VisionDetection]:
        """Detecta regiones compatibles con humo y calcula su nivel de confianza."""
        if frame is None or frame.size == 0:
            return []

        height, width = frame.shape[:2]
        frame_area = float(height * width)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # El humo tiende a presentar baja saturación y luminancia media-alta sin saturar en blanco puro.
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        smoke_mask = ((sat <= self.max_saturation) & (val >= self.min_value) & (val <= self.max_value)).astype(
            np.uint8
        ) * 255

        # Descartar fondos completamente planos evaluando contraste local frente al resto de la escena.
        if np.mean(smoke_mask > 0) > 0.85:
            return []

        if use_motion and self._prev_gray is not None and self._prev_gray.shape == gray.shape:
            diff = cv2.absdiff(gray, self._prev_gray)
            _, motion_mask = cv2.threshold(diff, 8, 255, cv2.THRESH_BINARY)
            smoke_mask = cv2.bitwise_and(smoke_mask, cv2.dilate(motion_mask, np.ones((7, 7), np.uint8)))
        self._prev_gray = gray

        kernel = np.ones((5, 5), np.uint8)
        cleaned = cv2.morphologyEx(smoke_mask, cv2.MORPH_OPEN, kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[VisionDetection] = []

        for contour in contours:
            area = cv2.contourArea(contour)
            area_ratio = area / frame_area
            if area_ratio < self.min_area_ratio:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            roi_gray = gray[y : y + h, x : x + w]
            roi_sat = sat[y : y + h, x : x + w]
            if roi_gray.size == 0:
                continue

            # Medida de difusión: bordes suaves (baja varianza de Laplaciano relativa) + baja saturación.
            lap_var = float(cv2.Laplacian(roi_gray, cv2.CV_64F).var())
            diffusion_score = max(0.0, min(1.0, 1.0 - (lap_var / 1500.0)))
            sat_score = max(0.0, min(1.0, 1.0 - (float(np.mean(roi_sat)) / 100.0)))
            size_score = max(0.0, min(1.0, area_ratio / 0.12))

            confianza = round(0.45 * sat_score + 0.35 * diffusion_score + 0.20 * size_score, 4)
            if confianza >= self.confidence_threshold:
                detections.append(
                    VisionDetection(
                        tipo="HUMO",
                        confianza=min(1.0, confianza),
                        bbox=(int(x), int(y), int(x + w), int(y + h)),
                    )
                )

        detections.sort(key=lambda d: d.confianza, reverse=True)
        return detections


class VisionAnalyzer:
    """Combina detección de personas y humo sobre un mismo frame."""

    def __init__(
        self,
        person_detector: PersonDetector | None = None,
        smoke_detector: SmokeDetector | None = None,
    ) -> None:
        self.person_detector = person_detector or PersonDetector()
        self.smoke_detector = smoke_detector or SmokeDetector()

    def analyze(
        self,
        frame: np.ndarray,
        *,
        detect_persons: bool = True,
        detect_smoke: bool = True,
    ) -> list[VisionDetection]:
        detections: list[VisionDetection] = []
        if detect_persons and self.person_detector.is_available:
            detections.extend(self.person_detector.detect(frame))
        if detect_smoke:
            detections.extend(self.smoke_detector.detect(frame))
        return detections
