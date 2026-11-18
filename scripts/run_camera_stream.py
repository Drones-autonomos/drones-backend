"""Publicador de cámara simulada hacia el stream de video en vivo (MJPEG/RTSP)."""

import argparse
import os
import subprocess
import time

import cv2
import httpx
import numpy as np


def _build_synthetic_frame(frame_idx: int, width: int = 640, height: int = 360) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = (32, 85, 42)
    x = (frame_idx * 12) % max(1, width - 80)
    cv2.rectangle(frame, (x, height // 2 - 30), (x + 60, height // 2 + 30), (200, 200, 200), -1)
    cv2.putText(
        frame,
        f"UAV SIM CAM | FRAME {frame_idx}",
        (16, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


def stream_to_backend(
    *,
    source: str,
    backend_url: str,
    token: str,
    fps: float = 10.0,
    jpeg_quality: int = 75,
    max_frames: int | None = None,
    loop: bool = True,
) -> int:
    """Lee una fuente de video/cámara y publica frames JPEG con reconexión automática."""
    use_synthetic = source == "synthetic"
    cap = None if use_synthetic else cv2.VideoCapture(int(source) if source.isdigit() else source)
    if cap is not None and not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir la fuente de cámara simulada: {source}")

    endpoint = f"{backend_url.rstrip('/')}/api/v1/video/frame"
    headers = {"Authorization": f"Bearer {token}"}
    interval = 1.0 / max(0.5, fps)
    sent = 0
    idx = 0

    try:
        with httpx.Client(timeout=5.0) as client:
            while max_frames is None or sent < max_frames:
                idx += 1
                if use_synthetic:
                    frame = _build_synthetic_frame(idx)
                else:
                    ok, frame = cap.read()
                    if not ok:
                        if loop:
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            continue
                        break

                ok_enc, encoded = cv2.imencode(
                    ".jpg",
                    frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)],
                )
                if not ok_enc:
                    continue

                h, w = frame.shape[:2]
                files = {"file": ("frame.jpg", encoded.tobytes(), "image/jpeg")}
                res = client.post(
                    endpoint,
                    params={"width": w, "height": h},
                    files=files,
                    headers=headers,
                )
                res.raise_for_status()
                sent += 1
                if max_frames is None or sent < max_frames:
                    time.sleep(interval)
    finally:
        if cap is not None:
            cap.release()
    return sent


def stream_to_rtsp(*, source: str, rtsp_url: str, fps: int = 15, bitrate: str = "900k") -> int:
    """Reenvía un video/cámara simulada hacia un servidor RTSP (ej. MediaMTX) con ffmpeg."""
    cmd = [
        "ffmpeg",
        "-re",
        "-stream_loop",
        "-1",
        "-i",
        source,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-b:v",
        bitrate,
        "-r",
        str(fps),
        "-f",
        "rtsp",
        rtsp_url,
    ]
    return subprocess.call(cmd)


def main() -> None:
    parser = argparse.ArgumentParser(description="Conectar cámara simulada al servidor de streaming")
    parser.add_argument("--source", default="data/sitl-demo.mp4", help="Ruta video, índice cámara o 'synthetic'")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("DRONE_API_TOKEN", ""))
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--quality", type=int, default=75)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--rtsp-url", default=None, help="Si se especifica, publica por RTSP vía ffmpeg")
    args = parser.parse_args()

    if args.rtsp_url:
        raise SystemExit(stream_to_rtsp(source=args.source, rtsp_url=args.rtsp_url, fps=int(args.fps)))

    if not args.token:
        raise SystemExit("Se requiere --token o DRONE_API_TOKEN para publicar frames")
    count = stream_to_backend(
        source=args.source,
        backend_url=args.backend_url,
        token=args.token,
        fps=args.fps,
        jpeg_quality=args.quality,
        max_frames=args.max_frames,
    )
    print(f"Frames transmitidos: {count}")


if __name__ == "__main__":
    main()
