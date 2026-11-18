"""Módulo de visión por computadora para procesamiento de video y detecciones."""

from app.vision.detector import PersonDetector, SmokeDetector, VisionAnalyzer, VisionDetection
from app.vision.pipeline import FramePacket, FramePipeline

__all__ = [
    "FramePacket",
    "FramePipeline",
    "PersonDetector",
    "SmokeDetector",
    "VisionAnalyzer",
    "VisionDetection",
]
