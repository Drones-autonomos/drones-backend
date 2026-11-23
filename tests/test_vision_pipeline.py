"""Pruebas para el pipeline de procesamiento de frames."""

from pathlib import Path

import cv2
import numpy as np

from app.vision.pipeline import FramePipeline


def test_pipeline_preprocess_and_save_evidence(tmp_path: Path):
    pipeline = FramePipeline(source=0, target_size=(320, 240), evidence_dir=tmp_path / "frames")
    raw = np.zeros((480, 640, 3), dtype=np.uint8)
    raw[100:200, 150:250] = (200, 200, 200)

    packets = list(pipeline.iter_from_arrays([raw]))
    assert len(packets) == 1
    assert packets[0].width == 320
    assert packets[0].height == 240

    annotated = pipeline.annotate(
        packets[0].frame,
        [{"tipo": "PERSONA", "confianza": 0.91, "bbox": (20, 20, 120, 180)}],
    )
    saved = Path(pipeline.save_evidence(annotated, prefix="test_det"))
    assert saved.exists()
    assert saved.stat().st_size > 0


def test_pipeline_reads_video_file(tmp_path: Path):
    video_path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10.0,
        (160, 120),
    )
    assert writer.isOpened()
    for i in range(4):
        frame = np.full((120, 160, 3), i * 40, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    pipeline = FramePipeline(source=str(video_path), target_size=(128, 128), evidence_dir=tmp_path)
    packets = list(pipeline.iter_frames(max_frames=3))
    assert len(packets) == 3
    assert all((p.width, p.height) == (128, 128) for p in packets)
