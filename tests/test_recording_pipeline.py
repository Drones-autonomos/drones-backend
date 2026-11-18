"""Pruebas de grabación continua con ffmpeg, metadata automática y estrés de segmentos."""

import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.recording_pipeline import ContinuousRecordingPipeline, RecordingUploader


def _create_synthetic_mp4(path: Path, seconds: int = 4) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=320x240:rate=10:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


def test_continuous_ffmpeg_recording_uploads_all_segments(client, admin_token, tmp_path: Path, monkeypatch):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg no disponible en el entorno")

    from app.api.v1.endpoints import recordings as rec_ep

    encrypted_dir = tmp_path / "encrypted_recordings"
    encrypted_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rec_ep, "STORAGE_DIR", str(encrypted_dir))

    source_video = tmp_path / "source.mp4"
    _create_synthetic_mp4(source_video, seconds=6)

    class _TestClientAdapter:
        def post(self, url: str, data: dict, files: dict):
            path = url.replace("http://testserver", "")
            return client.post(path, data=data, files=files)

    uploader = RecordingUploader(base_url="http://testserver", client=_TestClientAdapter())
    pipeline = ContinuousRecordingPipeline(
        output_dir=tmp_path / "segments",
        uploader=uploader,
        segment_seconds=1,
        vuelo_id=42,
    )

    summary = pipeline.run(str(source_video), poll_interval=0.1)
    assert summary["segments_uploaded"] >= 5
    assert summary["total_bytes"] > 0

    headers = {"Authorization": f"Bearer {admin_token}"}
    listed = client.get("/api/v1/recordings/?vuelo_id=42", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == summary["segments_uploaded"]
    assert all(r["vuelo_id"] == 42 for r in rows)
    assert all(len(r["checksum_sha256"]) == 64 for r in rows)
    assert all(r["duracion_segundos"] >= 1 for r in rows)

    # Verifica que el segmento cifrado se pueda reproducir descifrado
    first_id = rows[0]["id"]
    stream_res = client.get(f"/api/v1/recordings/{first_id}/stream", headers=headers)
    assert stream_res.status_code == 200
    assert len(stream_res.content) == rows[0]["tamano_bytes"]
