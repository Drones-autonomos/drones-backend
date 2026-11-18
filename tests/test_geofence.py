"""Pruebas para geocercas circulares/poligonales y rechazo de waypoints fuera de zona."""

from types import SimpleNamespace

import pytest

from app.services.drone_service import DroneService
from app.services.geofence_service import GeofenceSpec


def test_circular_geofence_rejects_outside_mission(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    # Geocerca centrada en UAQ Juriquilla, radio 250 m
    fence = client.post(
        "/api/v1/geofences/",
        json={
            "nombre": "Campus Juriquilla",
            "tipo": "CIRCULAR",
            "centro_lat": 20.70428,
            "centro_lon": -100.44358,
            "radio_metros": 250.0,
            "altitud_min_m": 2.0,
            "altitud_max_m": 120.0,
        },
        headers=headers,
    )
    assert fence.status_code == 201

    # Punto lejano (~5 km) debe rechazarse
    outside = client.post(
        "/api/v1/geofences/validate-point",
        json={"latitud": 20.75, "longitud": -100.44358, "altitud_metros": 15.0},
        headers=headers,
    )
    assert outside.status_code == 200
    assert outside.json()["permitido"] is False

    # Misión con waypoint fuera de geocerca -> 422
    bad_mission = client.post(
        "/api/v1/missions/",
        json={
            "nombre": "Misión Fuera de Geocerca",
            "waypoints": [
                {"orden_waypoint": 1, "latitud": 20.7043, "longitud": -100.4435, "altitud_metros": 15.0},
                {"orden_waypoint": 2, "latitud": 20.7500, "longitud": -100.4435, "altitud_metros": 15.0},
            ],
        },
        headers=headers,
    )
    assert bad_mission.status_code == 422
    assert "geocerca" in bad_mission.json()["detail"].lower()

    # Misión con ambos waypoints dentro -> 201
    ok_mission = client.post(
        "/api/v1/missions/",
        json={
            "nombre": "Misión Dentro de Geocerca",
            "waypoints": [
                {"orden_waypoint": 1, "latitud": 20.7043, "longitud": -100.4435, "altitud_metros": 15.0},
                {"orden_waypoint": 2, "latitud": 20.7048, "longitud": -100.4432, "altitud_metros": 20.0},
            ],
        },
        headers=headers,
    )
    assert ok_mission.status_code == 201


def test_polygon_geofence_and_toggle(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    fence = client.post(
        "/api/v1/geofences/",
        json={
            "nombre": "Polígono Facultad",
            "tipo": "POLIGONO",
            "poligono": [
                [20.7035, -100.4445],
                [20.7035, -100.4425],
                [20.7055, -100.4425],
                [20.7055, -100.4445],
            ],
        },
        headers=headers,
    )
    assert fence.status_code == 201
    fence_id = fence.json()["id"]

    inside = client.post(
        "/api/v1/geofences/validate-point",
        json={"latitud": 20.7045, "longitud": -100.4435, "altitud_metros": 20.0},
        headers=headers,
    )
    assert inside.json()["permitido"] is True

    outside = client.post(
        "/api/v1/geofences/validate-point",
        json={"latitud": 20.7080, "longitud": -100.4435, "altitud_metros": 20.0},
        headers=headers,
    )
    assert outside.json()["permitido"] is False

    toggled = client.patch(f"/api/v1/geofences/{fence_id}/toggle", headers=headers)
    assert toggled.status_code == 200
    assert toggled.json()["activa"] is False


def test_drone_controller_rejects_waypoint_outside_geofence():
    service = DroneService()
    service.vehicle = SimpleNamespace(
        last_heartbeat=0.1,
        armed=True,
        mode=SimpleNamespace(name="GUIDED"),
    )
    service.set_geofences(
        [
            GeofenceSpec(
                nombre="Zona Segura",
                tipo="CIRCULAR",
                centro_lat=20.70428,
                centro_lon=-100.44358,
                radio_metros=150.0,
            )
        ]
    )
    outside_wp = SimpleNamespace(latitud=20.7100, longitud=-100.4435, altitud_metros=15.0)
    with pytest.raises(ValueError, match="geocerca"):
        service.goto_waypoint(outside_wp)
