"""Pruebas de evaluación de precisión, ajuste de umbrales e integración visión-backend."""

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.vision.detector import PersonDetector, SmokeDetector, VisionAnalyzer
from app.vision.evaluate import LabeledSample, evaluate_detector, tune_threshold
from app.vision.pipeline import FramePipeline
from app.vision.runner import DetectionBackendClient, TelemetryPoint, VisionPipelineRunner


def _make_clean_frame() -> np.ndarray:
    frame = np.zeros((320, 320, 3), dtype=np.uint8)
    frame[:, :] = (35, 115, 45)
    return frame


def _make_smoke_frame() -> np.ndarray:
    frame = _make_clean_frame()
    cv2.ellipse(frame, (160, 160), (85, 60), 0, 0, 360, (190, 190, 190), -1)
    return cv2.GaussianBlur(frame, (29, 29), 0)


def test_evaluate_and_tune_smoke_thresholds():
    detector = SmokeDetector(confidence_threshold=0.45)
    samples = [
        LabeledSample(frame=_make_smoke_frame(), expected_present=True, label="HUMO", name="smoke-1"),
        LabeledSample(frame=_make_smoke_frame(), expected_present=True, label="HUMO", name="smoke-2"),
        LabeledSample(frame=_make_clean_frame(), expected_present=False, label="HUMO", name="clean-1"),
        LabeledSample(frame=_make_clean_frame(), expected_present=False, label="HUMO", name="clean-2"),
    ]

    metrics = evaluate_detector(samples, detector.detect, threshold=0.65, target_label="HUMO")
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.false_positive_rate == 0.0

    best_t, reports = tune_threshold(samples, detector.detect, target_label="HUMO")
    assert 0.50 <= best_t <= 0.85
    assert len(reports) == 7


def test_vision_runner_triggers_backend_event_and_alert(client, admin_token, tmp_path: Path):
    pipeline = FramePipeline(source=0, target_size=(320, 320), evidence_dir=tmp_path / "evidence")
    analyzer = VisionAnalyzer(
        person_detector=PersonDetector(model_path="models/nonexistent.onnx"),
        smoke_detector=SmokeDetector(confidence_threshold=0.65),
    )

    class _TestClientAdapter:
        def post(self, url: str, json: dict):
            path = url.replace("http://testserver", "")
            return client.post(path, json=json)

    backend_client = DetectionBackendClient(base_url="http://testserver", client=_TestClientAdapter())
    runner = VisionPipelineRunner(
        pipeline,
        analyzer,
        backend_client,
        telemetry_provider=lambda: TelemetryPoint(latitud=20.70428, longitud=-100.44358, vuelo_id=1),
        min_confidence=0.65,
    )

    packets = list(pipeline.iter_from_arrays([_make_smoke_frame()]))
    emitted = runner.process_packet(packets[0], timestamp_override=datetime(2026, 11, 17, 23, 15, 0))
    assert len(emitted) == 1
    assert emitted[0]["tipo"] == "HUMO"
    assert emitted[0]["evento_id"] is not None
    assert Path(emitted[0]["frame_url"]).exists()
    assert emitted[0]["e2e_ms"] < 2000.0

    alerts = client.get("/api/v1/alerts/?nivel_criticidad=CRITICA", headers={"Authorization": f"Bearer {admin_token}"})
    assert alerts.status_code == 200
    assert any(a["evento_id"] == emitted[0]["evento_id"] for a in alerts.json())
