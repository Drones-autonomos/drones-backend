"""Pruebas de streaming en vivo, snapshot, reconexión y WebSocket de telemetría."""

import cv2
import numpy as np

from app.services.video_stream_service import video_stream_service


def _sample_jpeg_bytes() -> bytes:
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    frame[:, :] = (30, 90, 180)
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    return buf.tobytes()


def test_video_stream_publish_snapshot_and_mjpeg(client, admin_token):
    video_stream_service.mark_offline()
    headers = {"Authorization": f"Bearer {admin_token}"}
    jpeg = _sample_jpeg_bytes()

    res_push = client.post(
        "/api/v1/video/frame?width=320&height=180",
        files={"file": ("frame.jpg", jpeg, "image/jpeg")},
        headers=headers,
    )
    assert res_push.status_code == 202
    assert res_push.json()["sequence"] >= 1

    info = client.get("/api/v1/video/stream-info")
    assert info.status_code == 200
    body = info.json()
    assert body["estado_camara"] == "ONLINE"
    assert body["resolucion"] == "320x180"
    assert body["frames_publicados"] >= 1

    snap = client.get("/api/v1/video/snapshot")
    assert snap.status_code == 200
    assert snap.headers["content-type"] == "image/jpeg"
    assert snap.content == jpeg

    live = client.get("/api/v1/video/live?max_frames=2")
    assert live.status_code == 200
    assert "multipart/x-mixed-replace" in live.headers["content-type"]
    assert live.content.count(b"--frame") == 2


def test_video_stream_tracks_reconnects(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    jpeg = _sample_jpeg_bytes()
    client.post(
        "/api/v1/video/frame?width=320&height=180",
        files={"file": ("f1.jpg", jpeg, "image/jpeg")},
        headers=headers,
    )
    before = client.get("/api/v1/video/stream-info").json()["reconexiones"]

    video_stream_service.mark_offline()
    client.post(
        "/api/v1/video/frame?width=320&height=180",
        files={"file": ("f2.jpg", jpeg, "image/jpeg")},
        headers=headers,
    )
    after = client.get("/api/v1/video/stream-info").json()["reconexiones"]
    assert after == before + 1


def test_video_websocket_telemetry_ping_and_status(client):
    with client.websocket_connect("/api/v1/video/ws/telemetry") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
        ws.send_text("status")
        payload = ws.receive_json()
        assert "connected" in payload
        assert "stream" in payload
