"""Integración del pipeline de visión con el endpoint de ingesta del backend."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.vision.detector import VisionAnalyzer, VisionDetection
from app.vision.pipeline import FramePacket, FramePipeline


@dataclass(slots=True)
class TelemetryPoint:
    """Coordenadas asociadas al frame al momento de la detección."""

    latitud: float
    longitud: float
    vuelo_id: int | None = None


class DetectionBackendClient:
    """Publica detecciones hacia `/api/v1/detections/ingest` vía HTTP."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        client: httpx.Client | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._external_client = client
        self.timeout = timeout

    def send_detection(
        self,
        detection: VisionDetection,
        telemetry: TelemetryPoint,
        *,
        frame_url: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict:
        payload = {
            "vuelo_id": telemetry.vuelo_id,
            "tipo": detection.tipo,
            "nivel_confianza": round(float(detection.confianza), 4),
            "frame_url": frame_url,
            "latitud": telemetry.latitud,
            "longitud": telemetry.longitud,
            "timestamp": (timestamp or datetime.now(UTC).replace(tzinfo=None)).isoformat(),
        }
        url = f"{self.base_url}/api/v1/detections/ingest"
        if self._external_client is not None:
            response = self._external_client.post(url, json=payload)
        else:
            with httpx.Client(timeout=self.timeout) as http_client:
                response = http_client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


class VisionPipelineRunner:
    """Ejecuta captura -> detección -> evidencia -> ingesta automática en backend."""

    def __init__(
        self,
        pipeline: FramePipeline,
        analyzer: VisionAnalyzer,
        backend_client: DetectionBackendClient,
        *,
        telemetry_provider: Callable[[], TelemetryPoint] | None = None,
        min_confidence: float = 0.65,
    ) -> None:
        self.pipeline = pipeline
        self.analyzer = analyzer
        self.backend_client = backend_client
        self.telemetry_provider = telemetry_provider or (
            lambda: TelemetryPoint(latitud=20.70428, longitud=-100.44358, vuelo_id=None)
        )
        self.min_confidence = min_confidence

    def process_packet(
        self,
        packet: FramePacket,
        *,
        timestamp_override: datetime | None = None,
    ) -> list[dict]:
        """Analiza un frame, guarda evidencia y envía las detecciones válidas al backend."""
        t0 = time.perf_counter()
        detections = [det for det in self.analyzer.analyze(packet.frame) if det.confianza >= self.min_confidence]
        if not detections:
            return []

        annotated = self.pipeline.annotate(packet.frame, [d.to_dict() for d in detections])
        evidence_path = self.pipeline.save_evidence(annotated, prefix=f"det_{packet.frame_id}")
        telemetry = self.telemetry_provider()

        emitted: list[dict] = []
        for det in detections:
            record = self.backend_client.send_detection(
                det,
                telemetry,
                frame_url=evidence_path,
                timestamp=timestamp_override or packet.timestamp,
            )
            record["e2e_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            emitted.append(record)
        return emitted
