from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.main import app
from app.models.mission import Mision, Ruta
from app.schemas.mission import MisionCreate
from app.services.drone_service import FlightCancelled
from app.services.mission_service import MissionError, MissionService, get_mission_service
from tests.conftest import TestingSessionLocal
from tests.test_missions import MISION_PAYLOAD


class DeferredThread:
    def __init__(self, target, args, **kwargs):
        self.target, self.args = target, args

    def start(self):
        pass

    def join(self, timeout=None):
        pass

    def run(self):
        self.target(*self.args)


class FakeDrone:
    def __init__(self):
        self.grounded = True
        self.route = []
        self.rtl_count = 0
        self.fail_navigation = False
        self.fail_landing = False
        self.connected = True

    def ensure_ready(self):
        if not self.connected or not self.grounded:
            raise RuntimeError("Vehículo no disponible")

    def arm_and_takeoff(self, altitude, cancel):
        if cancel.is_set():
            raise FlightCancelled()
        self.grounded = False
        self.altitude = altitude
        return True

    def goto_waypoint(self, waypoint, cancel):
        if self.fail_navigation:
            raise TimeoutError("No llegó al waypoint")
        if cancel.is_set():
            raise FlightCancelled()
        self.route.append((waypoint.latitud, waypoint.longitud, waypoint.altitud_metros))

    def is_grounded(self):
        return self.grounded

    def return_to_launch(self):
        self.rtl_count += 1
        return True

    def wait_landed(self):
        if self.fail_landing:
            raise TimeoutError("No aterrizó")
        self.grounded = True


@pytest.fixture()
def execution(db, admin_user):
    drone = FakeDrone()
    service = MissionService(TestingSessionLocal, drone, DeferredThread)

    def create(offset=0, schedule=None):
        mission = Mision(nombre="Ruta dinámica", creado_por=admin_user.id, horario_inicio_programado=schedule)
        mission.waypoints = [
            Ruta(orden_waypoint=i, latitud=20 + offset + i / 1000, longitud=-100, altitud_metros=10 + i) for i in (1, 2)
        ]
        db.add(mission)
        db.commit()
        return mission.id

    def read(mission_id):
        db.expire_all()
        return db.get(Mision, mission_id)

    return SimpleNamespace(service=service, drone=drone, create=create, read=read)


def test_runs_two_distinct_saved_routes(execution):
    e = execution
    for offset in (0, 1):
        mission_id = e.create(offset)
        e.service.start(mission_id)
        assert e.read(mission_id).estado == "EN_CURSO"
        assert e.read(mission_id).vehiculo_activo == 1
        e.service.worker.run()
        mission = e.read(mission_id)
        assert mission.estado == "FINALIZADA"
        assert mission.waypoints_completados == 2
        assert mission.iniciada_at and mission.finalizada_at
        assert mission.vehiculo_activo is None
    assert e.drone.route == [(20.001, -100, 11), (20.002, -100, 12), (21.001, -100, 11), (21.002, -100, 12)]
    assert e.drone.rtl_count == 2


def test_rejects_concurrent_and_repeated_start(execution):
    e = execution
    first, second = e.create(), e.create(1)
    e.service.start(first)
    with pytest.raises(MissionError, match="ocupado"):
        e.service.start(second)
    e.service.worker.run()
    with pytest.raises(MissionError, match="PROGRAMADAS"):
        e.service.start(first)
    assert e.read(second).estado == "PROGRAMADA"


def test_disconnected_drone_does_not_claim_mission(execution):
    e = execution
    mission_id = e.create()
    e.drone.connected = False
    with pytest.raises(MissionError) as error:
        e.service.start(mission_id)
    assert error.value.status_code == 503
    assert e.read(mission_id).estado == "PROGRAMADA"
    assert e.read(mission_id).vehiculo_activo is None


def test_cancel_before_takeoff_does_not_arm(execution):
    e = execution
    mission_id = e.create()
    e.service.start(mission_id)
    e.service.cancel(mission_id)
    assert e.read(mission_id).estado == "CANCELANDO"
    e.service.worker.run()
    assert e.read(mission_id).estado == "CANCELADA"
    assert e.drone.route == []
    assert e.drone.rtl_count == 0


def test_cancel_in_flight_stops_remaining_waypoints(execution):
    e = execution
    mission_id = e.create()
    original_goto = e.drone.goto_waypoint

    def goto(waypoint, cancel):
        original_goto(waypoint, cancel)
        e.service.cancel(mission_id)

    e.drone.goto_waypoint = goto
    e.service.start(mission_id)
    e.service.worker.run()
    assert e.read(mission_id).estado == "CANCELADA"
    assert e.read(mission_id).waypoints_completados == 1
    assert len(e.drone.route) == 1
    assert e.drone.rtl_count == 1


def test_navigation_failure_returns_home_and_records_failure(execution):
    e = execution
    mission_id = e.create()
    e.drone.fail_navigation = True
    e.service.start(mission_id)
    e.service.worker.run()
    assert e.read(mission_id).estado == "FALLIDA"
    assert e.read(mission_id).error_ejecucion
    assert e.read(mission_id).vehiculo_activo is None
    assert e.drone.rtl_count == 1


def test_unconfirmed_landing_keeps_reservation_across_restart(execution):
    e = execution
    first, second = e.create(), e.create(1)
    e.drone.fail_landing = True
    e.service.start(first)
    e.service.worker.run()
    assert e.read(first).estado == "RECUPERACION"
    assert e.read(first).vehiculo_activo == 1
    assert e.read(first).finalizada_at is None
    restarted = MissionService(TestingSessionLocal, e.drone, DeferredThread)
    with pytest.raises(MissionError, match="reserva"):
        restarted.start(second)
    with pytest.raises(MissionError):
        restarted.confirm_landed(first)
    e.drone.grounded = True
    restarted.confirm_landed(first)
    assert e.read(first).estado == "FALLIDA"
    assert e.read(first).vehiculo_activo is None
    restarted.start(second)


def test_cannot_confirm_landed_while_worker_active(execution):
    e = execution
    mission_id = e.create()
    e.service.start(mission_id)
    with pytest.raises(MissionError, match="activo"):
        e.service.confirm_landed(mission_id)


def test_database_reservation_blocks_second_executor(execution):
    e = execution
    first, second = e.create(), e.create(1)
    e.service.start(first)
    other = MissionService(TestingSessionLocal, e.drone, DeferredThread)
    with pytest.raises(MissionError, match="reserva"):
        other.start(second)


def test_thread_start_failure_releases_reservation(execution):
    e = execution
    mission_id = e.create()
    e.service.thread_factory = Mock(side_effect=RuntimeError("No threads"))
    with pytest.raises(MissionError):
        e.service.start(mission_id)
    assert e.read(mission_id).estado == "FALLIDA"
    assert e.read(mission_id).vehiculo_activo is None
    assert e.service.active_id is None


def test_manual_control_and_missions_exclude_each_other(execution):
    e = execution
    mission_id = e.create()
    with e.service.manual_control():
        with pytest.raises(MissionError, match="ocupado"):
            e.service.start(mission_id)
    e.service.start(mission_id)
    with pytest.raises(MissionError, match="ocupado"):
        with e.service.manual_control():
            pytest.fail("Manual command must not execute")


def test_emergency_rtl_cancels_active_mission(execution):
    e = execution
    mission_id = e.create()
    e.service.start(mission_id)
    send_rtl = Mock()
    assert e.service.emergency_rtl(send_rtl)
    send_rtl.assert_not_called()
    assert e.service.cancel_event.is_set()
    assert e.read(mission_id).estado == "CANCELANDO"


def test_scheduler_starts_only_due_missions_and_never_repeats(execution):
    e = execution
    now = datetime.now(UTC)
    future = e.create(schedule=(now + timedelta(days=1)).replace(tzinfo=None))
    manual = e.create()
    due = e.create(schedule=(now - timedelta(minutes=1)).replace(tzinfo=None))
    e.service.run_due(now)
    assert e.service.active_id == due
    e.service.worker.run()
    e.service.run_due(now)
    assert e.service.active_id is None
    assert e.read(future).estado == e.read(manual).estado == "PROGRAMADA"
    assert e.drone.rtl_count == 1


def test_invalid_legacy_route_is_not_started(execution, db):
    e = execution
    mission_id = e.create()
    mission = e.read(mission_id)
    mission.waypoints[1].orden_waypoint = 1
    db.commit()
    with pytest.raises(MissionError) as error:
        e.service.start(mission_id)
    assert error.value.status_code == 422
    assert e.read(mission_id).estado == "PROGRAMADA"


@pytest.mark.parametrize("orders", [(1, 1), (1, 3), (2, 3)])
def test_route_requires_unique_consecutive_order(orders):
    payload = {
        **MISION_PAYLOAD,
        "waypoints": [
            {**waypoint, "orden_waypoint": order}
            for waypoint, order in zip(MISION_PAYLOAD["waypoints"], orders, strict=True)
        ],
    }
    with pytest.raises(ValidationError):
        MisionCreate(**payload)


def test_schedule_normalizes_timezone_and_route_order():
    mission = MisionCreate(
        **{
            **MISION_PAYLOAD,
            "horario_inicio_programado": "2026-10-25T10:00:00-06:00",
            "waypoints": list(reversed(MISION_PAYLOAD["waypoints"])),
        }
    )
    assert mission.horario_inicio_programado == datetime(2026, 10, 25, 16)
    assert [wp.orden_waypoint for wp in mission.waypoints] == [1, 2]


@pytest.mark.parametrize("role,status", [(None, 401), ("guardia", 403), ("admin", 202)])
def test_start_api_permissions(client, request, role, status, admin_token):
    service = app.dependency_overrides[get_mission_service]()
    service.drone = FakeDrone()
    service.thread_factory = DeferredThread
    created = client.post(
        "/api/v1/missions/", json=MISION_PAYLOAD, headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    headers = {} if role is None else {"Authorization": f"Bearer {request.getfixturevalue(role + '_token')}"}
    response = client.post(f"/api/v1/missions/{created['id']}/start", headers=headers)
    assert response.status_code == status
    if status == 202:
        assert response.json()["estado"] == "EN_CURSO"
        assert response.json()["waypoints_completados"] == 0
        service.worker.run()
        result = client.get(f"/api/v1/missions/{created['id']}", headers=headers).json()
        assert result["estado"] == "FINALIZADA"
        assert result["waypoints_completados"] == 2


def test_start_missing_mission(client, admin_token):
    result = client.post("/api/v1/missions/999/start", headers={"Authorization": f"Bearer {admin_token}"})
    assert result.status_code == 404


def test_real_worker_cancels_without_blocking_requests(tmp_path):
    from threading import Event

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base_class import Base
    from app.models.user import Rol, Usuario

    engine = create_engine(f"sqlite:///{tmp_path / 'execution.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as db:
        role = Rol(nombre="ADMIN")
        db.add(role)
        db.flush()
        user = Usuario(nombre="Admin", email="worker@test.com", password_hash="unused", rol_id=role.id)
        db.add(user)
        db.flush()
        mission = Mision(nombre="Real worker", creado_por=user.id)
        mission.waypoints = [
            Ruta(orden_waypoint=i, latitud=20, longitud=-100 + i / 1000, altitud_metros=10) for i in (1, 2)
        ]
        db.add(mission)
        db.flush()
        mission_id = mission.id
    drone = FakeDrone()
    entered, release = Event(), Event()

    def blocked_goto(waypoint, cancel):
        entered.set()
        assert release.wait(3)
        if cancel.is_set():
            raise FlightCancelled()

    drone.goto_waypoint = blocked_goto
    service = MissionService(sessions, drone)
    try:
        service.start(mission_id)
        assert entered.wait(3)
        service.cancel(mission_id)
        with sessions() as db:
            assert db.get(Mision, mission_id).estado == "CANCELANDO"
        release.set()
        service.worker.join(timeout=3)
        assert not service.worker.is_alive()
        with sessions() as db:
            result = db.get(Mision, mission_id)
            assert result.estado == "CANCELADA"
            assert result.vehiculo_activo is None
        assert drone.rtl_count == 1
    finally:
        release.set()
        service.shutdown()
        engine.dispose()


def test_scheduler_lifecycle_stops_cleanly(execution):
    e = execution
    called = Mock(side_effect=e.service.stop_event.set)
    e.service.run_due = called
    e.service.start_scheduler(interval=0.01)
    e.service.scheduler.join(timeout=3)
    assert not e.service.scheduler.is_alive()
    called.assert_called_once()
    e.service.shutdown()


def test_progress_persistence_failure_triggers_rtl(execution):
    e = execution
    mission_id = e.create()
    e.service._progress = Mock(side_effect=RuntimeError("DB failed"))
    e.service.start(mission_id)
    e.service.worker.run()
    assert e.read(mission_id).estado == "FALLIDA"
    assert e.drone.rtl_count == 1


def test_final_persistence_failure_preserves_reservation(execution):
    e = execution
    mission_id = e.create()
    e.service._finish = Mock(side_effect=RuntimeError("DB failed"))
    e.service.start(mission_id)
    e.service.worker.run()
    assert e.read(mission_id).vehiculo_activo == 1
    assert e.service.active_id is None
    assert e.drone.grounded


def test_unique_reservation_constraint(execution, db):
    from sqlalchemy.exc import IntegrityError

    e = execution
    first, second = e.create(), e.create(1)
    e.read(first).vehiculo_activo = 1
    db.commit()
    e.read(second).vehiculo_activo = 1
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_api_cancel_and_manual_flight_conflict(client, admin_token, guardia_token, monkeypatch):
    from app.api.v1.endpoints import drone as endpoint

    service = app.dependency_overrides[get_mission_service]()
    service.drone = FakeDrone()
    service.thread_factory = DeferredThread
    manual = Mock()
    monkeypatch.setattr(endpoint, "drone_service", manual)
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post("/api/v1/missions/", json=MISION_PAYLOAD, headers=headers).json()
    mission_id = created["id"]
    assert client.post(f"/api/v1/missions/{mission_id}/start", headers=headers).status_code == 202
    response = client.post("/api/v1/drone/takeoff", json={"altitude": 10}, headers=headers)
    assert response.status_code == 409
    manual.arm_and_takeoff.assert_not_called()
    cancel = client.post(f"/api/v1/missions/{mission_id}/cancel", headers={"Authorization": f"Bearer {guardia_token}"})
    assert cancel.status_code == 200
    assert cancel.json()["estado"] == "CANCELANDO"
    service.worker.run()
    assert client.get(f"/api/v1/missions/{mission_id}", headers=headers).json()["estado"] == "CANCELADA"


@pytest.mark.parametrize("role,expected", [(None, 401), ("guardia", 403), ("admin", 200)])
def test_api_recovery_permissions(client, admin_token, request, role, expected):
    service = app.dependency_overrides[get_mission_service]()
    service.drone = FakeDrone()
    service.drone.fail_landing = True
    service.thread_factory = DeferredThread
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post("/api/v1/missions/", json=MISION_PAYLOAD, headers=headers).json()
    mission_id = created["id"]
    client.post(f"/api/v1/missions/{mission_id}/start", headers=headers)
    service.worker.run()
    service.drone.grounded = True
    headers = {} if role is None else {"Authorization": f"Bearer {request.getfixturevalue(role + '_token')}"}
    result = client.post(f"/api/v1/missions/{mission_id}/confirm-landed", headers=headers)
    assert result.status_code == expected
    if expected == 200:
        assert result.json()["estado"] == "FALLIDA"
