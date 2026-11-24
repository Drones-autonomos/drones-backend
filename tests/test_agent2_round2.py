"""Pruebas de Ronda 2 del Agente 2: LAND real, estado pausado y estaciones en BD."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.main import app
from app.models.audit import Auditoria
from app.models.charging_base import EstacionCarga
from app.models.flight_log import BitacoraVuelo
from app.models.mission import Mision, Ruta
from app.services import drone_service as drone_module
from app.services.charging_base_service import ChargingBaseService
from app.services.drone_service import drone_service
from app.services.mission_service import MissionError, MissionService, get_mission_service
from tests.conftest import TestingSessionLocal
from tests.test_mission_execution import DeferredThread, FakeDrone


@pytest.fixture()
def fake_dronekit(monkeypatch):
    monkeypatch.setattr(drone_module, "_DRONEKIT_AVAILABLE", True)
    monkeypatch.setattr(
        drone_module,
        "VehicleMode",
        lambda name: SimpleNamespace(name=name),
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
# Persistencia de estaciones_carga
# ---------------------------------------------------------------------------


def test_ensure_default_stations_is_idempotent(db):
    service = ChargingBaseService()
    service.ensure_default_stations(db)
    service.ensure_default_stations(db)

    rows = db.query(EstacionCarga).order_by(EstacionCarga.codigo).all()
    assert [row.codigo for row in rows] == ["HELIPUERTO_NORTE", "HELIPUERTO_SUR"]
    assert rows[0].nombre.startswith("Helipuerto Base Norte")
    assert rows[1].nombre.startswith("Helipuerto Base Sur")
    assert rows[0].domo_estado == "Abierto"
    assert rows[1].domo_estado == "Cerrado"


def test_charging_endpoints_persist_dock_cycle(client, admin_token, db, grounded_vehicle):
    list_res = client.get(
        "/api/v1/drone/charging-bases",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 2
    assert db.query(EstacionCarga).count() == 2

    res = client.post(
        "/api/v1/drone/charging-base/dock-recharge",
        params={"station_id": "helipuerto_sur", "target_pct": 100},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.json()["estado"] == "CHARGED"

    row = (
        db.query(EstacionCarga)
        .filter(EstacionCarga.codigo == "HELIPUERTO_SUR")
        .first()
    )
    assert row is not None
    assert row.estado == "CHARGED"
    assert row.bateria_porcentaje == 100
    assert row.ciclos_completados >= 1
    assert row.ultimo_acoplamiento_at is not None


# ---------------------------------------------------------------------------
# Estado pausado y conexión real
# ---------------------------------------------------------------------------


def test_telemetry_current_reports_paused_cycle(client, admin_token, flying_vehicle):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post("/api/v1/drone/pause", headers=headers)
    assert res.status_code == 200
    res = client.get("/api/v1/telemetry/current", headers=headers)
    assert res.status_code == 200
    assert res.json()["pausado"] is True

    res = client.post("/api/v1/drone/resume", headers=headers)
    assert res.status_code == 200
    res = client.get("/api/v1/telemetry/current", headers=headers)
    assert res.status_code == 200
    assert res.json()["pausado"] is False


def test_connection_status_is_offline_without_vehicle(client, guardia_token):
    original = drone_service.vehicle
    drone_service.vehicle = None
    try:
        res = client.get(
            "/api/v1/drone/connection-status",
            headers={"Authorization": f"Bearer {guardia_token}"},
        )
    finally:
        drone_service.vehicle = original
    assert res.status_code == 200
    assert res.json()["estado"] == "OFFLINE"
    assert res.json()["bateria_porcentaje"] is None


# ---------------------------------------------------------------------------
# Parada de emergencia: cancela la misión y aterriza en LAND
# ---------------------------------------------------------------------------


def test_emergency_stop_always_lands_with_active_mission(
    client,
    admin_token,
    admin_user,
    db,
    flying_vehicle,
):
    mission = Mision(
        creado_por=admin_user.id,
        nombre="Misión activa para parada",
        descripcion="Prueba",
        estado="EN_CURSO",
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)

    service = SimpleNamespace(active_id=mission.id, cancelled=None)

    def cancel(mission_id):
        service.cancelled = mission_id
        service.active_id = None

    service.cancel = cancel
    original_override = app.dependency_overrides.get(get_mission_service)
    app.dependency_overrides[get_mission_service] = lambda: service
    try:
        res = client.post(
            "/api/v1/drone/emergency-stop",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    finally:
        if original_override is None:
            app.dependency_overrides.pop(get_mission_service, None)
        else:
            app.dependency_overrides[get_mission_service] = original_override

    assert res.status_code == 200
    assert res.json()["detenido"] is True
    assert res.json()["resultado"]["modo"] == "LAND"
    assert service.cancelled == mission.id
    assert drone_service.vehicle.mode.name == "LAND"

    bitacora = (
        db.query(BitacoraVuelo)
        .filter(BitacoraVuelo.vuelo_id == mission.id)
        .order_by(BitacoraVuelo.id.desc())
        .first()
    )
    assert bitacora is not None
    assert bitacora.estado_final == "PARADA_EMERGENCIA"

    audit = (
        db.query(Auditoria)
        .filter(Auditoria.accion == "PARADA_EMERGENCIA_LAND")
        .order_by(Auditoria.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.usuario_id == admin_user.id
    assert str(mission.id) in audit.detalle


# ---------------------------------------------------------------------------
# Reintento de misiones terminadas (POST /missions/{id}/retry)
# ---------------------------------------------------------------------------


def _terminal_mission(db, admin_user, estado="FALLIDA"):
    mission = Mision(
        creado_por=admin_user.id,
        nombre="Misión terminada",
        estado=estado,
        error_ejecucion="Error durante la ejecución" if estado == "FALLIDA" else None,
    )
    mission.waypoints = [
        Ruta(
            orden_waypoint=i,
            latitud=20 + i / 1000,
            longitud=-100,
            altitud_metros=10 + i,
        )
        for i in (1, 2)
    ]
    db.add(mission)
    db.commit()
    db.refresh(mission)
    return mission


def test_retry_clones_terminal_mission_and_starts(db, admin_user):
    service = MissionService(TestingSessionLocal, FakeDrone(), DeferredThread)
    original = _terminal_mission(db, admin_user)

    clone_id = service.retry(original.id, ejecutado_por=admin_user.id)

    clone = db.get(Mision, clone_id)
    assert clone.id != original.id
    assert clone.estado == "EN_CURSO"
    assert clone.ejecutado_por == admin_user.id
    assert clone.es_recurrente is False
    assert len(clone.waypoints) == 2
    assert service.active_id == clone_id

    db.refresh(original)
    assert original.estado == "FALLIDA"  # el historial sellado no se toca


def test_retry_rejects_non_terminal_mission(db, admin_user):
    service = MissionService(TestingSessionLocal, FakeDrone(), DeferredThread)
    mission = _terminal_mission(db, admin_user, estado="PROGRAMADA")

    with pytest.raises(MissionError):
        service.retry(mission.id)


def test_retry_leaves_clone_programada_when_drone_unavailable(db, admin_user):
    drone = FakeDrone()
    drone.connected = False
    service = MissionService(TestingSessionLocal, drone, DeferredThread)
    original = _terminal_mission(db, admin_user)

    with pytest.raises(MissionError):
        service.retry(original.id)

    clone = db.query(Mision).filter(Mision.id != original.id).one()
    assert clone.estado == "PROGRAMADA"
    assert len(clone.waypoints) == 2


def test_retry_endpoint_keeps_clone_when_drone_offline(client, admin_token, db, admin_user):
    original = _terminal_mission(db, admin_user)

    res = client.post(
        f"/api/v1/missions/{original.id}/retry",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Sin vehículo conectado el arranque se rechaza, pero la ruta clonada
    # queda PROGRAMADA para iniciarla cuando haya enlace.
    assert res.status_code == 503
    clone = db.query(Mision).filter(Mision.id != original.id).one()
    assert clone.estado == "PROGRAMADA"
    assert len(clone.waypoints) == 2
