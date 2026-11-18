"""Pruebas de pérdida de señal (corte de enlace MAVLink), failsafe GCS y recuperación RTL."""

from types import SimpleNamespace

import pytest

from app.models.mission import Mision, Ruta
from app.services.drone_service import DroneService, SignalLossError, drone_service
from app.services.mission_service import MissionService
from tests.conftest import TestingSessionLocal


def test_configure_gcs_failsafe_sets_ardupilot_parameter(client, admin_token):
    original = drone_service.vehicle
    try:
        params = {}
        drone_service.vehicle = SimpleNamespace(last_heartbeat=0.2, parameters=params)
        res = client.post(
            "/api/v1/drone/failsafe?enabled=true",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        assert res.json() == {"fs_gcs_enable": 1, "accion_perdida_enlace": "RTL"}
        assert params["FS_GCS_ENABLE"] == 1
    finally:
        drone_service.vehicle = original


def test_signal_loss_raises_specific_error_and_triggers_recovery(db, admin_user):
    class LinkLossVehicle:
        def __init__(self):
            self.last_heartbeat = 0.1
            self.armed = False
            self.mode = SimpleNamespace(name="STABILIZE")
            self.is_armable = True
            self.parameters = {}
            self.location = SimpleNamespace(
                global_relative_frame=SimpleNamespace(lat=20.70428, lon=-100.44358, alt=0.0)
            )
            self.battery = SimpleNamespace(level=85, voltage=15.6)
            self.groundspeed = 0.0
            self.heading = 0

        def simple_takeoff(self, alt):
            self.location.global_relative_frame.alt = alt

        def simple_goto(self, target):
            # Simula corte de enlace justo tras enviar el waypoint
            self.last_heartbeat = 12.0

    vehicle = LinkLossVehicle()
    ticks = {"t": 0.0}

    def clock():
        ticks["t"] += 0.5
        return ticks["t"]

    drone = DroneService(poll_interval=0.0, clock=clock, sleep=lambda _: None)
    drone.vehicle = vehicle
    drone.configure_gcs_failsafe(enabled=True)
    assert vehicle.parameters["FS_GCS_ENABLE"] == 1

    with pytest.raises(SignalLossError):
        vehicle.last_heartbeat = 9.0
        drone.ensure_connected()

    # Reiniciamos enlace, iniciamos misión y simulamos corte durante navegación -> queda en RECUPERACION
    vehicle.last_heartbeat = 0.1
    mission = Mision(nombre="Misión Corte Enlace", creado_por=admin_user.id)
    mission.waypoints = [
        Ruta(orden_waypoint=1, latitud=20.70435, longitud=-100.44358, altitud_metros=10.0),
        Ruta(orden_waypoint=2, latitud=20.70450, longitud=-100.44358, altitud_metros=10.0),
    ]
    db.add(mission)
    db.commit()
    db.refresh(mission)

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

        def join(self, timeout=None):
            pass

    service = MissionService(TestingSessionLocal, drone=drone, thread_factory=ImmediateThread)
    service.start(mission.id)
    db.expire_all()
    saved = db.get(Mision, mission.id)
    assert saved.estado == "RECUPERACION"
    assert saved.vehiculo_activo == 1

    # Tras restablecer enlace y aterrizar en RTL, el operador confirma aterrizaje y libera reserva
    vehicle.last_heartbeat = 0.1
    vehicle.armed = False
    vehicle.location.global_relative_frame.alt = 0.0
    service.confirm_landed(mission.id)
    db.expire_all()
    recovered = db.get(Mision, mission.id)
    assert recovered.estado == "FALLIDA"
    assert recovered.vehiculo_activo is None
