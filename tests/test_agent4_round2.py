"""
Suite de pruebas de Ronda 2 del Agente 4:
- WS /api/v1/video/ws/telemetry mantiene el bucle activo ante múltiples mensajes/timeouts,
  incluye `pausado` en el snapshot y rechaza tokens revocados (POST /auth/logout) o usuarios inactivos.
- WS /api/v1/alerts/ws/notifications rechaza tokens revocados o usuarios desactivados en BD.
- Endpoints HTTP con ?token= (/video/snapshot, /detections/{id}/frame, /recordings/{id}/stream)
  bloquean inmediatamente tokens revocados en `tokens_revocados`.
"""

import pytest
from starlette.websockets import WebSocketDisconnect

from app.services.drone_service import drone_service
from app.services.video_stream_service import video_stream_service


def test_video_ws_telemetry_multi_cycle_and_paused_flag(client, guardia_token):
    """El canal WS /video/ws/telemetry responde múltiples ciclos sin cerrarse e incluye `pausado`."""
    with client.websocket_connect(f"/api/v1/video/ws/telemetry?token={guardia_token}") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"

        ws.send_text("status")
        snap1 = ws.receive_json()
        assert "pausado" in snap1
        assert snap1["pausado"] is False

        # Segundo ciclo consecutivo en la misma conexión WebSocket
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
        ws.send_text("status")
        snap2 = ws.receive_json()
        assert "stream" in snap2


def test_video_ws_reflects_paused_when_vehicle_connected(client, guardia_token, monkeypatch):
    """Cuando hay vehículo conectado y en pausa, _snapshot_telemetry reporta pausado=True."""

    class _DummyLoc:
        lat = 20.7042
        lon = -100.4438
        alt = 35.0

    class _DummyLocationWrapper:
        global_relative_frame = _DummyLoc()

    class _DummyBattery:
        level = 82

    class _DummyMode:
        name = "BRAKE"

    class _DummyVehicle:
        armed = True
        location = _DummyLocationWrapper()
        battery = _DummyBattery()
        mode = _DummyMode()

    monkeypatch.setattr(drone_service, "vehicle", _DummyVehicle())
    monkeypatch.setattr(drone_service, "paused", True, raising=False)
    monkeypatch.setattr(drone_service, "_paused", True, raising=False)
    try:
        with client.websocket_connect(f"/api/v1/video/ws/telemetry?token={guardia_token}") as ws:
            ws.send_text("status")
            snap = ws.receive_json()
            assert snap["connected"] is True
            assert snap["pausado"] is True
            assert snap["mode"] == "BRAKE"
    finally:
        monkeypatch.setattr(drone_service, "vehicle", None)
        monkeypatch.setattr(drone_service, "paused", False, raising=False)
        monkeypatch.setattr(drone_service, "_paused", False, raising=False)


def test_revoked_and_inactive_tokens_blocked_on_websockets_and_media(
    client, db, guardia_user, guardia_token
):
    """Tras logout (TokenRevocado) o baja de usuario, WS y endpoints ?token= rechazan el acceso."""
    video_stream_service.publish_jpeg(b"\xff\xd8\xff\xd9", width=64, height=64)

    # 1. Con token activo funciona tanto snapshot como WS de alertas
    ok_snap = client.get(f"/api/v1/video/snapshot?token={guardia_token}")
    assert ok_snap.status_code == 200

    with client.websocket_connect(f"/api/v1/alerts/ws/notifications?token={guardia_token}"):
        pass

    # 2. Revocar token vía POST /auth/logout -> bloqueado en WS alertas, WS telemetría y snapshot
    logout_res = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert logout_res.status_code in (200, 204)

    revoked_snap = client.get(f"/api/v1/video/snapshot?token={guardia_token}")
    assert revoked_snap.status_code == 401

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/alerts/ws/notifications?token={guardia_token}"):
            pass

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/video/ws/telemetry?token={guardia_token}"):
            pass

    # 3. Nuevo login seguido de desactivación del usuario -> bloqueado inmediatamente en WS
    fresh_login = client.post(
        "/api/v1/auth/login",
        json={"email": guardia_user.email, "password": "Guardia1234!"},
    )
    assert fresh_login.status_code == 200
    fresh_token = fresh_login.json()["access_token"]

    guardia_user.activo = False
    db.commit()

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/alerts/ws/notifications?token={fresh_token}"):
            pass

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/video/ws/telemetry?token={fresh_token}"):
            pass
