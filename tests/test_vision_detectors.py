"""Pruebas unitarias y de integración para detectores de personas y humo."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.vision.detector import PersonDetector, SmokeDetector, VisionAnalyzer


def test_person_detector_parses_yolo_tensor():
    detector = PersonDetector(model_path="models/nonexistent.onnx", confidence_threshold=0.5)
    tensor = np.zeros((1, 84, 5), dtype=np.float32)
    # Candidato 1: persona en el centro con confianza 0.92
    tensor[0, 0, 1] = 320.0
    tensor[0, 1, 1] = 320.0
    tensor[0, 2, 1] = 100.0
    tensor[0, 3, 1] = 200.0
    tensor[0, 4, 1] = 0.92
    # Candidato 2: debajo del umbral
    tensor[0, 4, 2] = 0.25

    detections = detector.parse_yolo_output(tensor, frame_width=640, frame_height=640)
    assert len(detections) == 1
    assert detections[0].tipo == "PERSONA"
    assert detections[0].confianza == pytest.approx(0.92, abs=1e-4)
    assert detections[0].bbox == (270, 220, 370, 420)


def test_person_detector_real_onnx_on_demo_image():
    model_path = Path("models/yolov8n.onnx")
    demo_image = Path("data/person-demo.jpg")
    if not model_path.exists() or not demo_image.exists():
        pytest.skip("Modelo ONNX o imagen demo no disponibles en el entorno")

    detector = PersonDetector(model_path=model_path, confidence_threshold=0.45)
    frame = cv2.imread(str(demo_image))
    assert frame is not None
    detections = detector.detect(frame)
    assert len(detections) >= 1
    assert any(d.tipo == "PERSONA" and d.confianza >= 0.70 for d in detections)


def test_smoke_detector_distinguishes_plume_from_clean_scene():
    detector = SmokeDetector(confidence_threshold=0.65)

    # Escena limpia (césped verde oscuro sin humo)
    clean_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    clean_frame[:, :] = (35, 110, 40)
    assert detector.detect(clean_frame) == []

    # Escena con nube grisácea difusa (humo)
    smoke_frame = clean_frame.copy()
    cv2.ellipse(smoke_frame, (320, 220), (130, 90), 0, 0, 360, (185, 185, 185), -1)
    smoke_frame = cv2.GaussianBlur(smoke_frame, (31, 31), 0)

    detections = detector.detect(smoke_frame)
    assert len(detections) >= 1
    assert detections[0].tipo == "HUMO"
    assert detections[0].confianza >= 0.65


def test_vision_analyzer_combines_detectors():
    clean_frame = np.zeros((320, 320, 3), dtype=np.uint8)
    clean_frame[:, :] = (40, 120, 40)
    cv2.ellipse(clean_frame, (160, 150), (75, 55), 0, 0, 360, (180, 180, 180), -1)
    clean_frame = cv2.GaussianBlur(clean_frame, (25, 25), 0)

    analyzer = VisionAnalyzer(
        person_detector=PersonDetector(model_path="models/nonexistent.onnx"),
        smoke_detector=SmokeDetector(confidence_threshold=0.60),
    )
    results = analyzer.analyze(clean_frame)
    assert any(det.tipo == "HUMO" for det in results)
