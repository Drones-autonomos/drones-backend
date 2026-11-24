"""Pruebas del Agente 2: control en vivo, telemetría enriquecida y helipuertos."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.models.flight_log import BitacoraVuelo
from app.services import drone_service as drone_module
from app.services.charging_base_service import ChargingBaseService, charging_base_service
from app.services.drone_service import drone_service
from app.services.telemetry_service import capture_vehicle_snapshot


@pytest.fixture()
def fake_dronekit(monkeypatch):
    monkeypatch.setattr(drone_module, "_DRONEKIT_AVAILABLE", True)
    monkeypatch.setattr(
        drone_module,
        "VehicleMode",
        lambda name: SimpleNamespace(name=name),
        raising=False,
    )
    monkeypatch.setattr(
        drone_module,
        "LocationGlobalRelative",
        lambda lat, lon, alt: SimpleNamespace(lat=lat, lon=lon, alt=alt),
        raising=False,
    )


@pytest.fixture()
def flying_vehicle(fake_dronekit):
    original = drone_service.vehicle
    original_paused = drone_service.paused
    drone_service.paused = False
    drone_service._paused_target = None
    drone_service.vehicle = Mock(
        armed=True,
        last_heartbeat=0.1,
        mode=SimpleNamespace(name="GUIDED"),
        battery=SimpleNamespace(level=75, voltage=15.8),
        gps_0=SimpleNamespace(fix_type=3, satellites_visible=12),
        parameters={"FS_GCS_ENABLE": 1},
        location=SimpleNamespace(
            global_relative_frame=SimpleNamespace(lat=20.70428, lon=-100.44358, alt=25.0)
        ),
        attitude=SimpleNamespace(pitch=0.1, roll=0.0, yaw=1.0),
        groundspeed=4.2,
        heading=90,
        is_armable=True,
    )
    yield drone_service.vehicle
    drone_service.vehicle = original
    drone_service.paused = original_paused
    drone_service._paused_target = None


@pytest.fixture()
def grounded_vehicle(fake_dronekit):
    original = drone_service.vehicle
    drone_service.vehicle = SimpleNamespace(
        armed=False,
        last_heartbeat=0.1,
        battery=SimpleNamespace(level=40, voltage=14.9),
        location=SimpleNamespace(
            global_relative_frame=SimpleNamespace(lat=20.705145, lon=-100.444093, alt=0.1)
        ),
    )
    yield drone_service.vehicle
    drone_service.vehicle = original


# ---------------------------------------------------------------------------
# Telemetría enriquecida
# ---------------------------------------------------------------------------


def test_snapshot_enriched_fields(flying_vehicle):
    snap = capture_vehicle_snapshot(drone_service)
    assert snap["connected"] is True
    assert snap["satelites_gps"] == 12
    assert snap["gps_fix_type"] == 3
    assert snap["tilt_grados"] == pytest.approx(5.73, abs=0.05)
    assert snap["senal_rf_porcentaje"] == pytest.approx(98, abs=2)
    assert snap["latencia_ms"] == pytest.approx(100, abs=5)
    assert snap["zona_actual"] == "Campus FIF"
    assert snap["estado_zona"] == "Monitoreo"
    assert snap["failsafe_gcs_activo"] is True


def test_snapshot_disconnected_has_enriched_keys():
    snap = capture_vehicle_snapshot(SimpleNamespace(vehicle=None))
    assert snap["connected"] is False
    for key in (
        "viento_velocidad_kmh",
        "satelites_gps",
        "gps_fix_type",
        "tilt_grados",
        "senal_rf_porcentaje",
        "latencia_ms",
        "zona_actual",
        "estado_zona",
        "failsafe_gcs_activo",
    ):
        assert snap[key] is None


def test_snapshot_zone_outside_campus(flying_vehicle):
    flying_vehicle.location.global_relative_frame.lat = 20.72
    snap = capture_vehicle_snapshot(drone_service)
    assert snap["zona_actual"] == "Fuera de zona"
    assert snap["estado_zona"] == "Fuera de cobertura"


# ---------------------------------------------------------------------------
# Control en vivo: pause / resume / emergency-stop / disconnect
# ---------------------------------------------------------------------------


def test_pause_requires_auth(client):
    res = client.post("/api/v1/drone/pause")
    assert res.status_code == 401


def test_pause_rejects_when_not_flying(client, guardia_token, grounded_vehicle):
    res = client.post(
        "/api/v1/drone/pause",
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert res.status_code == 503
    assert "pausar" in res.json()["detail"].lower()


def test_pause_and_resume_cycle(client, admin_token, flying_vehicle):
    res = client.post(
        "/api/v1/drone/pause",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.json() == {"pausado": True, "modo": "BRAKE"}
    assert drone_service.paused is True
    assert drone_service.vehicle.mode.name == "BRAKE"

    res = client.post(
        "/api/v1/drone/resume",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.json()["pausado"] is False
    assert drone_service.paused is False
    assert drone_service.vehicle.mode.name == "GUIDED"


def test_resume_reissues_paused_target(flying_vehicle):
    target = SimpleNamespace(lat=20.7, lon=-100.44, alt=20)
    drone_service.paused = True
    drone_service._paused_target = target
    result = drone_service.resume_flight()
    assert result["pausado"] is False
    flying_vehicle.simple_goto.assert_called_once_with(target)


def test_pause_falls_back_to_loiter(flying_vehicle):
    drone_service._set_mode("BRAKE")
    flying_vehicle.mode.name = "LOITER"  # firmware que no acepta BRAKE
    service_calls = []

    original_set_mode = drone_service._set_mode

    def rejecting_brake(name):
        original_set_mode(name)
        if name == "BRAKE":
            flying_vehicle.mode.name = "LOITER"
        service_calls.append(name)

    drone_service._set_mode = rejecting_brake
    try:
        result = drone_service.pause_flight()
    finally:
        drone_service._set_mode = original_set_mode
    assert result["modo"] == "LOITER"
    assert service_calls == ["BRAKE", "LOITER"]


def test_emergency_stop_lands_and_logs(client, admin_token, flying_vehicle, db):
    res = client.post(
        "/api/v1/drone/emergency-stop",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.json()["detenido"] is True
    assert drone_service.vehicle.mode.name == "LAND"

    registro = (
        db.query(BitacoraVuelo)
        .filter(BitacoraVuelo.estado_final == "PARADA_EMERGENCIA")
        .order_by(BitacoraVuelo.id.desc())
        .first()
    )
    assert registro is not None
    assert "parada de emergencia" in registro.incidentes.lower()


def test_disconnect_requires_admin(client, guardia_token, admin_token, flying_vehicle):
    res = client.post(
        "/api/v1/drone/disconnect",
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert res.status_code == 403

    res = client.post(
        "/api/v1/drone/disconnect",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert drone_service.vehicle is None


# ---------------------------------------------------------------------------
# Prevuelo y failsafe
# ---------------------------------------------------------------------------


def test_preflight_disconnected(client, guardia_token):
    original = drone_service.vehicle
    drone_service.vehicle = None
    try:
        res = client.get(
            "/api/v1/drone/preflight-check",
            headers={"Authorization": f"Bearer {guardia_token}"},
        )
    finally:
        drone_service.vehicle = original
    assert res.status_code == 200
    body = res.json()
    assert body["ready"] is False
    assert body["checks"]["conexion"] is False


def test_preflight_connected(client, admin_token, flying_vehicle):
    res = client.get(
        "/api/v1/drone/preflight-check",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ready"] is True
    assert body["checks"]["enlace"] is True
    assert body["checks"]["bateria"] is True
    assert body["detalles"]["satelites"] == 12


def test_get_failsafe_status(client, guardia_token, flying_vehicle):
    res = client.get(
        "/api/v1/drone/failsafe",
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert res.status_code == 200
    assert res.json() == {"connected": True, "enabled": True}


def test_get_failsafe_disconnected(client, guardia_token):
    original = drone_service.vehicle
    drone_service.vehicle = None
    try:
        res = client.get(
            "/api/v1/drone/failsafe",
            headers={"Authorization": f"Bearer {guardia_token}"},
        )
    finally:
        drone_service.vehicle = original
    assert res.status_code == 200
    assert res.json()["connected"] is False


# ---------------------------------------------------------------------------
# Seguridad de los endpoints de conectividad
# ---------------------------------------------------------------------------


def test_connection_endpoints_require_auth(client):
    res = client.get("/api/v1/drone/connection-status")
    assert res.status_code == 401

    res = client.post(
        "/api/v1/drone/connection-event",
        json={"estado_enlace": "ONLINE"},
    )
    assert res.status_code == 401


def test_connection_event_requires_admin(client, guardia_token, admin_token):
    res = client.post(
        "/api/v1/drone/connection-event",
        json={"estado_enlace": "ONLINE"},
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert res.status_code == 403

    res = client.post(
        "/api/v1/drone/connection-event",
        json={"estado_enlace": "ONLINE"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 201


def test_connection_status_with_guard(client, guardia_token):
    res = client.get(
        "/api/v1/drone/connection-status",
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert res.status_code == 200
    assert "estado" in res.json()


# ---------------------------------------------------------------------------
# Helipuertos / estaciones de carga
# ---------------------------------------------------------------------------


def test_list_charging_bases(client, guardia_token):
    res = client.get(
        "/api/v1/drone/charging-bases",
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert res.status_code == 200
    estaciones = res.json()
    assert len(estaciones) == 2
    codigos = {e["codigo"] for e in estaciones}
    assert codigos == {"HELIPUERTO_NORTE", "HELIPUERTO_SUR"}
    for estacion in estaciones:
        assert "domo_estado" in estacion
        assert "sistema_aterrizaje" in estacion
        assert "voltaje_v" in estacion
        assert "temperatura_c" in estacion


def test_charging_base_by_station_id(client, admin_token):
    res = client.get(
        "/api/v1/drone/charging-base",
        params={"station_id": "helipuerto_sur"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert "Base 2" in res.json()["nombre"]
    assert res.json()["domo_estado"] == "Cerrado"


def test_charging_base_unknown_station(client, admin_token):
    res = client.get(
        "/api/v1/drone/charging-base",
        params={"station_id": "no-existe"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 503
    assert "desconocida" in res.json()["detail"].lower()


def test_dock_at_secondary_station(client, admin_token, grounded_vehicle):
    res = client.post(
        "/api/v1/drone/charging-base/dock-recharge",
        params={"station_id": "helipuerto_sur"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["estado"] == "CHARGED"
    assert body["codigo"] == "HELIPUERTO_SUR"
    assert body["distancia_home_m"] < 3.0

    estacion_sur = charging_base_service.get_status("helipuerto_sur")
    assert estacion_sur["ciclos_completados"] >= 1


def test_dock_rejects_when_far_from_station(client, admin_token, grounded_vehicle):
    service = ChargingBaseService()
    fake_drone = SimpleNamespace(
        is_grounded=lambda: True,
        vehicle=SimpleNamespace(
            battery=SimpleNamespace(level=50),
            location=SimpleNamespace(
                global_relative_frame=SimpleNamespace(lat=20.71, lon=-100.44, alt=0.0)
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="base de carga"):
        service.dock_and_recharge(fake_drone, station_id="helipuerto_sur")
