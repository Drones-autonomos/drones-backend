"""Pruebas para límites normativos en script DroneKit, controlador y settings dinámicos."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from scripts.drone_backend import validate_flight_plan

from app.core.normative import NormativeConfig, get_normative_config, update_normative_config
from app.services.drone_service import DroneService


@pytest.fixture(autouse=True)
def reset_normative_config():
    original = get_normative_config()
    yield
    update_normative_config(original)


def test_script_validate_flight_plan_rejects_normative_violations():
    validate_flight_plan(altitude_m=20.0, weight_kg=2.5, flight_time=datetime(2026, 11, 17, 12, 0))

    with pytest.raises(ValueError, match="RNF-07"):
        validate_flight_plan(altitude_m=220.0, weight_kg=2.5, flight_time=datetime(2026, 11, 17, 12, 0))

    with pytest.raises(ValueError, match="peso"):
        validate_flight_plan(altitude_m=20.0, weight_kg=6.5, flight_time=datetime(2026, 11, 17, 12, 0))

    with pytest.raises(ValueError, match="RNF-02"):
        validate_flight_plan(altitude_m=20.0, weight_kg=2.5, flight_time=datetime(2026, 11, 17, 3, 0))


def test_drone_service_goto_waypoint_enforces_altitude_limit():
    service = DroneService()
    service.vehicle = SimpleNamespace(
        last_heartbeat=0.1,
        armed=True,
        mode=SimpleNamespace(name="GUIDED"),
    )
    bad_wp = SimpleNamespace(latitud=20.7043, longitud=-100.4435, altitud_metros=210.0)
    with pytest.raises(ValueError, match="RNF-07"):
        service.goto_waypoint(bad_wp)


def test_dynamic_normative_settings_affect_mission_validation(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.put(
        "/api/v1/settings/operating-window",
        json={
            "altitud_minima_m": 2.0,
            "altitud_maxima_m": 80.0,
            "peso_maximo_kg": 4.0,
            "hora_apertura": "07:00",
            "hora_cierre": "22:00",
        },
        headers=headers,
    )
    assert res.status_code == 200
    assert isinstance(get_normative_config(), NormativeConfig)

    # 90m supera el nuevo límite de 80m configurado por ADMIN
    mission_res = client.post(
        "/api/v1/missions/",
        json={
            "nombre": "Misión Límite Dinámico",
            "peso_dron_kg": 3.0,
            "waypoints": [
                {"orden_waypoint": 1, "latitud": 20.7043, "longitud": -100.4435, "altitud_metros": 90.0},
                {"orden_waypoint": 2, "latitud": 20.7045, "longitud": -100.4434, "altitud_metros": 50.0},
            ],
        },
        headers=headers,
    )
    assert mission_res.status_code == 422
