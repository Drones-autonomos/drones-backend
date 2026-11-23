"""Módulo de visión por computadora para procesamiento de video y detecciones."""

from app.vision.detector import PersonDetector, SmokeDetector, VisionAnalyzer, VisionDetection
from app.vision.evaluate import EvaluationMetrics, LabeledSample, evaluate_detector, tune_threshold
from app.vision.pipeline import FramePacket, FramePipeline
from app.vision.runner import DetectionBackendClient, TelemetryPoint, VisionPipelineRunner

__all__ = [
    "DetectionBackendClient",
    "EvaluationMetrics",
    "FramePacket",
    "FramePipeline",
    "LabeledSample",
    "PersonDetector",
    "SmokeDetector",
    "TelemetryPoint",
    "VisionAnalyzer",
    "VisionDetection",
    "VisionPipelineRunner",
    "evaluate_detector",
    "tune_threshold",
]
