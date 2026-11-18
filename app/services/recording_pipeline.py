"""Pipeline de grabación continua con ffmpeg y envío automático de metadata por segmento."""

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import httpx


@dataclass(slots=True)
class SegmentUploadResult:
    segment_path: str
    duracion_segundos: int
    tamano_bytes: int
    recording_id: int | None
    checksum_sha256: str


def measure_video_duration_seconds(video_path: Path, fallback_seconds: int = 1) -> int:
    """Calcula la duración entera en segundos de un segmento MP4 usando OpenCV."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return max(1, fallback_seconds)
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        if fps > 0 and frames > 0:
            return max(1, round(frames / fps))
        return max(1, fallback_seconds)
    finally:
        cap.release()


class RecordingUploader:
    """Envía cada segmento cerrado y su metadata hacia `/api/v1/recordings/upload`."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        client: httpx.Client | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client
        self.timeout = timeout

    def upload_segment(
        self,
        segment_path: Path,
        *,
        vuelo_id: int | None,
        duracion_segundos: int,
    ) -> dict:
        url = f"{self.base_url}/api/v1/recordings/upload"
        data: dict[str, str] = {"duracion_segundos": str(max(1, duracion_segundos))}
        if vuelo_id is not None:
            data["vuelo_id"] = str(vuelo_id)

        with segment_path.open("rb") as fh:
            files = {"file": (segment_path.name, fh, "video/mp4")}
            if self._client is not None:
                res = self._client.post(url, data=data, files=files)
            else:
                with httpx.Client(timeout=self.timeout) as http_client:
                    res = http_client.post(url, data=data, files=files)
        res.raise_for_status()
        return res.json()


class ContinuousRecordingPipeline:
    """Graba un flujo continuo en segmentos MP4 con ffmpeg y registra su metadata al cerrar cada uno."""

    def __init__(
        self,
        output_dir: str | Path,
        uploader: RecordingUploader,
        *,
        segment_seconds: int = 10,
        vuelo_id: int | None = None,
        ffmpeg_bin: str = "ffmpeg",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.uploader = uploader
        self.segment_seconds = max(1, segment_seconds)
        self.vuelo_id = vuelo_id
        self.ffmpeg_bin = ffmpeg_bin

    def build_ffmpeg_command(self, source: str, *, duration_limit: int | None = None) -> list[str]:
        pattern = str(self.output_dir / "segment_%05d.mp4")
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-loglevel",
            "error",
            "-i",
            source,
        ]
        if duration_limit is not None:
            cmd.extend(["-t", str(duration_limit)])
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-sc_threshold",
                "0",
                "-force_key_frames",
                f"expr:gte(t,n_forced*{self.segment_seconds})",
                "-f",
                "segment",
                "-segment_time",
                str(self.segment_seconds),
                "-reset_timestamps",
                "1",
                pattern,
            ]
        )
        return cmd

    def flush_completed_segments(
        self,
        uploaded: set[Path],
        *,
        include_latest: bool = False,
        on_upload: Callable[[SegmentUploadResult], None] | None = None,
    ) -> list[SegmentUploadResult]:
        """Sube segmentos ya cerrados; deja el último en escritura salvo al terminar ffmpeg."""
        segments = sorted(self.output_dir.glob("segment_*.mp4"))
        ready = segments if include_latest else segments[:-1]
        results: list[SegmentUploadResult] = []
        for seg in ready:
            if seg in uploaded or seg.stat().st_size == 0:
                continue
            duration = measure_video_duration_seconds(seg, fallback_seconds=self.segment_seconds)
            payload = self.uploader.upload_segment(
                seg,
                vuelo_id=self.vuelo_id,
                duracion_segundos=duration,
            )
            uploaded.add(seg)
            result = SegmentUploadResult(
                segment_path=str(seg),
                duracion_segundos=duration,
                tamano_bytes=int(payload.get("tamano_bytes", seg.stat().st_size)),
                recording_id=payload.get("id"),
                checksum_sha256=str(payload.get("checksum_sha256", "")),
            )
            if on_upload is not None:
                on_upload(result)
            results.append(result)
        return results

    def run(
        self,
        source: str,
        *,
        duration_limit: int | None = None,
        poll_interval: float = 0.25,
    ) -> dict:
        """Ejecuta ffmpeg y sube cada segmento cerrado conforme avanza la grabación."""
        t0 = time.perf_counter()
        cmd = self.build_ffmpeg_command(source, duration_limit=duration_limit)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        uploaded: set[Path] = set()
        results: list[SegmentUploadResult] = []

        try:
            while proc.poll() is None:
                results.extend(self.flush_completed_segments(uploaded, include_latest=False))
                time.sleep(poll_interval)
            _, stderr = proc.communicate(timeout=10)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg falló (código {proc.returncode}): {stderr.decode(errors='ignore')}")
            results.extend(self.flush_completed_segments(uploaded, include_latest=True))
        finally:
            if proc.poll() is None:
                proc.terminate()

        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "segments_uploaded": len(results),
            "total_bytes": sum(r.tamano_bytes for r in results),
            "elapsed_seconds": elapsed,
            "recording_ids": [r.recording_id for r in results],
        }
