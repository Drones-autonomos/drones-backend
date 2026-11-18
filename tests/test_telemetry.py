"""Pruebas para endpoints de telemetría en vivo y bitácora persistente."""

from types import SimpleNamespace

from app.services.drone_service import drone_service


def test_current_telemetry_disconnected(client, guardia_token):
    drone_service.vehicle = None
    headers = {"Authorization": f"Bearer {guardia_token}"}
    res = client.get("/api/v1/telemetry/current", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["connected"] is False
    assert data["estado_enlace"] == "DESCONECTADO"


def test_current_telemetry_connected_vehicle(client, guardia_token):
    original = drone_service.vehicle
    try:
        drone_service.vehicle = SimpleNamespace(
            last_heartbeat=0.2,
            armed=True,
            mode=SimpleNamespace(name="GUIDED"),
            groundspeed=5.4,
            heading=180,
            battery=SimpleNamespace(level=87, voltage=15.8),
            location=SimpleNamespace(global_relative_frame=SimpleNamespace(lat=20.70428, lon=-100.44358, alt=14.5)),
        )
        res = client.get("/api/v1/telemetry/current", headers={"Authorization": f"Bearer {guardia_token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["connected"] is True
        assert data["armado"] is True
        assert data["modo_vuelo"] == "GUIDED"
        assert data["bateria_porcentaje"] == 87.0
        assert data["estado_enlace"] == "OK"
    finally:
        drone_service.vehicle = original


def test_telemetry_log_create_and_filter(client, admin_token, guardia_token):
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    guard_headers = {"Authorization": f"Bearer {guardia_token}"}

    # Guardia no puede crear entradas manualmente en la bitácora
    denied = client.post(
        "/api/v1/telemetry/log",
        json={"latitud": 20.704, "longitud": -100.443, "altitud_metros": 12.0, "armado": True},
        headers=guard_headers,
    )
    assert denied.status_code == 403

    # Admin sí registra entrada
    created = client.post(
        "/api/v1/telemetry/log",
        json={
            "latitud": 20.70428,
            "longitud": -100.44358,
            "altitud_metros": 15.0,
            "bateria_porcentaje": 92.0,
            "voltaje_bateria": 16.1,
            "velocidad_tierra_ms": 4.8,
            "rumbo_grados": 90.0,
            "modo_vuelo": "GUIDED",
            "armado": True,
            "estado_enlace": "OK",
            "heartbeat_age_s": 0.3,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201

    # Guardia puede consultar bitácora filtrada por estado_enlace
    listed = client.get("/api/v1/telemetry/log?estado_enlace=OK", headers=guard_headers)
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["bateria_porcentaje"] == 92.0
    assert items[0]["modo_vuelo"] == "GUIDED"
