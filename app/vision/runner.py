"""Integración del pipeline de visión con el endpoint de ingesta del backend."""

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.vision.detector import VisionAnalyzer, VisionDetection
from app.vision.pipeline import FramePacket, FramePipeline


@dataclass(slots=True)
class TelemetryPoint:
    """Coordenadas asociadas al frame al momento de la detección."""

    latitud: float
    longitud: float
    vuelo_id: int | None = None
    altitud_metros: float | None = None


class DetectionBackendClient:
    """Publica detecciones hacia `/api/v1/detections/ingest` vía HTTP."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        client: httpx.Client | None = None,
        timeout: float = 5.0,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._external_client = client
        self.timeout = timeout
        self.api_key = api_key

    def send_detection(
        self,
        detection: VisionDetection,
        telemetry: TelemetryPoint,
        *,
        frame_url: str | None = None,
        checksum_sha256: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict:
        payload: dict = {
            "vuelo_id": telemetry.vuelo_id,
            "tipo": detection.tipo,
            "nivel_confianza": round(float(detection.confianza), 4),
            "frame_url": frame_url,
            "latitud": telemetry.latitud,
            "longitud": telemetry.longitud,
            "timestamp": (timestamp or datetime.now(UTC).replace(tzinfo=None)).isoformat(),
        }
        if telemetry.altitud_metros is not None:
            payload["altitud_metros"] = float(telemetry.altitud_metros)
        if checksum_sha256 is not None:
            payload["checksum_sha256"] = checksum_sha256

        url = f"{self.base_url}/api/v1/detections/ingest"
        headers = {"X-Ingestion-Key": self.api_key} if self.api_key else None
        if self._external_client is not None:
            if headers:
                response = self._external_client.post(url, json=payload, headers=headers)
            else:
                response = self._external_client.post(url, json=payload)
        else:
            with httpx.Client(timeout=self.timeout) as http_client:
                response = http_client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


class VisionPipelineRunner:
    """Ejecuta captura -> detección -> anonimización facial -> evidencia -> ingesta."""

    def __init__(
        self,
        pipeline: FramePipeline,
        analyzer: VisionAnalyzer,
        backend_client: DetectionBackendClient,
        *,
        telemetry_provider: Callable[[], TelemetryPoint] | None = None,
        min_confidence: float = 0.65,
        apply_face_blur: bool = True,
    ) -> None:
        self.pipeline = pipeline
        self.analyzer = analyzer
        self.backend_client = backend_client
        self.telemetry_provider = telemetry_provider or (
            lambda: TelemetryPoint(latitud=20.70428, longitud=-100.44358, vuelo_id=None)
        )
        self.min_confidence = min_confidence
        self.apply_face_blur = apply_face_blur

    def process_packet(
        self,
        packet: FramePacket,
        *,
        timestamp_override: datetime | None = None,
    ) -> list[dict]:
        """Analiza un frame, difumina rostros si aplica, sella evidencia y la envía al backend."""
        t0 = time.perf_counter()
        detections = [det for det in self.analyzer.analyze(packet.frame) if det.confianza >= self.min_confidence]
        if not detections:
            return []

        base_frame = self.pipeline.blur_faces(packet.frame) if self.apply_face_blur else packet.frame
        annotated = self.pipeline.annotate(base_frame, [d.to_dict() for d in detections])
        evidence_path = self.pipeline.save_evidence(annotated, prefix=f"det_{packet.frame_id}")
        checksum = hashlib.sha256(Path(evidence_path).read_bytes()).hexdigest()
        telemetry = self.telemetry_provider()

        emitted: list[dict] = []
        for det in detections:
            record = self.backend_client.send_detection(
                det,
                telemetry,
                frame_url=evidence_path,
                checksum_sha256=checksum,
                timestamp=timestamp_override or packet.timestamp,
            )
            record["e2e_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            emitted.append(record)
        return emitted
