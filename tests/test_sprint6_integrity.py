import pytest
from fastapi import status
from app.models.flight_log import BitacoraVuelo
from app.models.audit import Auditoria

def test_bitacora_and_audit_are_immutable(db):
    log = BitacoraVuelo(estado_final="COMPLETADO", duracion_segundos=120)
    db.add(log)
    db.commit()

    # Intentar modificar debe lanzar excepción
    log.duracion_segundos = 999
    with pytest.raises(ValueError, match="inmutable"):
        db.commit()
    db.rollback()

    # Intentar eliminar debe lanzar excepción
    with pytest.raises(ValueError, match="inmutable"):
        db.delete(log)
        db.commit()
    db.rollback()

def test_mission_rejected_when_crossing_geofence(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    # 1. Crear zona de exclusión rectangular
    client.post(
        "/api/v1/geofences/",
        json={"nombre": "Zona Restringida Norte", "lat_min": 20.58, "lat_max": 20.60, "lon_min": -100.40, "lon_max": -100.38},
        headers=headers
    )
    # 2. Intentar crear misión que cruza esa zona
    res = client.post(
        "/api/v1/missions/",
        json={
            "nombre": "Vuelo Invasor",
            "horario_inicio_programado": "2026-11-16T10:00:00",
            "peso_dron_kg": 2.0,
            "waypoints": [
                {"orden_waypoint": 1, "latitud": 20.57, "longitud": -100.39, "altitud_metros": 30.0},
                {"orden_waypoint": 2, "latitud": 20.61, "longitud": -100.39, "altitud_metros": 30.0}
            ]
        },
        headers=headers
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST