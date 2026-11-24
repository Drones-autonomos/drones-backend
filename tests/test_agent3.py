"""Pruebas del Agente 3: misiones, recurrencia, scheduler, geocercas y zonas de exclusión.

Cubre:
- Campos extendidos de misión (recurrencia, helipuertos, duración, batería,
  sensor, evitación de exclusión) y hover_segundos por waypoint.
- Validación de la ventana operativa convirtiendo timestamps con zona a
  America/Mexico_City antes de comparar contra 06:00-23:00 local.
- Edición completa de misión PROGRAMADA (PUT reemplaza waypoints y días).
- DELETE de misiones en estados permitidos (PROGRAMADA/CANCELADA/FALLIDA).
- GET/PUT /missions/scheduler (interruptor real del planificador autónomo).
- CRUD de /exclusion-zones con clasificación y metadatos, y sus reglas de
  bloqueo (restringida, tope de altitud, advertencia no bloqueante).
- PUT /geofences/{id} y /exclusion-zones/{id} + toggle.
- ejecutado_por al iniciar misión y clonación de la siguiente recurrencia.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.geofence import ZonaExclusion
from app.models.mission import Mision, Ruta
from app.services.geofence_service import evaluate_route_against_zones
from app.services.mission_service import MissionError, MissionService
from tests.conftest import TestingSessionLocal
from tests.test_mission_execution import DeferredThread, FakeDrone

# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

WP_A = {"orden_waypoint": 1, "latitud": 20.7043, "longitud": -100.4435, "altitud_metros": 20.0}
WP_B = {"orden_waypoint": 2, "latitud": 20.7048, "longitud": -100.4432, "altitud_metros": 20.0}

MISSION_MIN = {
    "nombre": "Patrulla Base Agent3",
    "waypoints": [WP_A, WP_B],
}

ZONA_CAMPUS = {
    "nombre": "Zona Rectoría",
    "lat_min": 20.7040,
    "lat_max": 20.7050,
    "lon_min": -100.4440,
    "lon_max": -100.4430,
}


def _create_mission(client, token, **overrides):
    r = client.post(
        "/api/v1/missions/",
        json={**MISSION_MIN, **overrides},
        headers={"Authorization": f"Bearer {token}"},
    )
    return r


def _create_zone(client, token, **overrides):
    r = client.post(
        "/api/v1/exclusion-zones/",
        json={**ZONA_CAMPUS, **overrides},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Creación con campos extendidos y validación de ventana horaria
# ---------------------------------------------------------------------------


def test_create_mission_with_extended_fields(client, admin_token):
    """POST /missions/ persiste recurrencia, helipuertos, duración, batería,
    sensor, evitación y hover_segundos por waypoint."""
    payload = {
        "nombre": "Patrullaje Completo Agent3",
        "descripcion": "Misión con metadatos completos",
        "horario_inicio_programado": "2026-10-01T18:30:00",
        "horario_fin_programado": "2026-10-01T19:00:00",
        "duracion_estimada_min": 32,
        "helipuerto_salida": "Helipuerto Norte",
        "helipuerto_llegada": "Helipuerto Sur",
        "es_recurrente": True,
        "dias_semana": ["lun", "Mié", "vie"],
        "evitacion_exclusion": False,
        "bateria_minima_pct": 55,
        "sensor_optico": "RGB 4K + IR",
        "waypoints": [
            {**WP_A, "hover_segundos": 12.5},
            WP_B,
        ],
    }
    r = client.post(
        "/api/v1/missions/",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["horario_fin_programado"] is not None
    assert data["duracion_estimada_min"] == 32
    assert data["helipuerto_salida"] == "Helipuerto Norte"
    assert data["helipuerto_llegada"] == "Helipuerto Sur"
    assert data["es_recurrente"] is True
    # "Mié" se normaliza sin acento a "mie"
    assert data["dias_semana"] == ["lun", "mie", "vie"]
    assert data["evitacion_exclusion"] is False
    assert data["bateria_minima_pct"] == 55
    assert data["sensor_optico"] == "RGB 4K + IR"
    assert data["waypoints"][0]["hover_segundos"] == 12.5
    assert data["waypoints"][1]["hover_segundos"] == 0.0


def test_schedule_utc_inside_local_window_accepted(client, admin_token):
    """Un timestamp con zona (toISOString del navegador) se evalúa en hora local.
    15:00Z = 09:00 en America/Mexico_City → dentro de la ventana."""
    r = _create_mission(
        client, admin_token, horario_inicio_programado="2026-10-01T15:00:00Z"
    )
    assert r.status_code == 201, r.text


def test_schedule_utc_outside_local_window_rejected(client, admin_token):
    """10:30Z = 04:30 local → fuera de la ventana 06:00-23:00 → 422."""
    r = _create_mission(
        client, admin_token, horario_inicio_programado="2026-10-01T10:30:00Z"
    )
    assert r.status_code == 422
    assert "ventana operativa" in str(r.json()["detail"]).lower()


def test_schedule_naive_inside_window_still_accepted(client, admin_token):
    """Los timestamps naive se siguen interpretando como hora local directa."""
    r = _create_mission(
        client, admin_token, horario_inicio_programado="2026-10-01T22:00:00"
    )
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# Edición de misión PROGRAMADA (PUT /missions/{id})
# ---------------------------------------------------------------------------


def test_update_mission_replaces_waypoints(client, admin_token, db):
    """PUT reemplaza los waypoints preservando hover_segundos."""
    r = _create_mission(client, admin_token)
    assert r.status_code == 201
    mision_id = r.json()["id"]

    nuevos = [
        {"orden_waypoint": 1, "latitud": 20.7044, "longitud": -100.4436, "altitud_metros": 25.0,
         "hover_segundos": 5.0},
        {"orden_waypoint": 2, "latitud": 20.7046, "longitud": -100.4434, "altitud_metros": 25.0},
        {"orden_waypoint": 3, "latitud": 20.7047, "longitud": -100.4433, "altitud_metros": 25.0},
    ]
    res = client.put(
        f"/api/v1/missions/{mision_id}",
        json={"waypoints": nuevos},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    wps = res.json()["waypoints"]
    assert len(wps) == 3
    assert [w["orden_waypoint"] for w in wps] == [1, 2, 3]
    assert wps[0]["hover_segundos"] == 5.0
    assert wps[0]["altitud_metros"] == 25.0

    db.expire_all()
    assert db.query(Ruta).filter(Ruta.mision_id == mision_id).count() == 3


def test_update_mission_dias_semana_persists(client, admin_token):
    """PUT dias_semana escribe el JSON nuevo (regresión: antes leía el valor
    viejo del modelo y la edición era un no-op)."""
    r = _create_mission(client, admin_token, es_recurrente=True, dias_semana=["lun"])
    assert r.status_code == 201
    mision_id = r.json()["id"]

    res = client.put(
        f"/api/v1/missions/{mision_id}",
        json={"dias_semana": ["sab", "dom"], "es_recurrente": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["dias_semana"] == ["sab", "dom"]


def test_update_mission_metadata_fields(client, admin_token):
    r = _create_mission(client, admin_token)
    mision_id = r.json()["id"]
    res = client.put(
        f"/api/v1/missions/{mision_id}",
        json={
            "helipuerto_salida": "Helipuerto Este",
            "duracion_estimada_min": 21,
            "bateria_minima_pct": 60,
            "sensor_optico": "Térmica + IR",
            "evitacion_exclusion": False,
            "horario_fin_programado": "2026-10-01T20:00:00",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["helipuerto_salida"] == "Helipuerto Este"
    assert data["duracion_estimada_min"] == 21
    assert data["bateria_minima_pct"] == 60
    assert data["sensor_optico"] == "Térmica + IR"
    assert data["evitacion_exclusion"] is False
    assert data["horario_fin_programado"].startswith("2026-10-01T20:00")


# ---------------------------------------------------------------------------
# DELETE /missions/{id}
# ---------------------------------------------------------------------------


def test_delete_programmed_mission(client, admin_token):
    r = _create_mission(client, admin_token)
    mision_id = r.json()["id"]

    res = client.delete(
        f"/api/v1/missions/{mision_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 204
    assert (
        client.get(
            f"/api/v1/missions/{mision_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        ).status_code
        == 404
    )


def test_delete_mission_forbidden_for_guardia(client, admin_token, guardia_token):
    r = _create_mission(client, admin_token)
    res = client.delete(
        f"/api/v1/missions/{r.json()['id']}",
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert res.status_code == 403


def test_delete_cancelled_mission_allowed(client, admin_token):
    r = _create_mission(client, admin_token)
    mision_id = r.json()["id"]
    client.post(
        f"/api/v1/missions/{mision_id}/cancel",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    res = client.delete(
        f"/api/v1/missions/{mision_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 204


def test_delete_mission_in_course_conflicts(client, admin_token, db):
    """Una misión EN_CURSO (o con reserva activa) no puede eliminarse → 409."""
    r = _create_mission(client, admin_token)
    mision_id = r.json()["id"]
    mision = db.get(Mision, mision_id)
    mision.estado = "EN_CURSO"
    mision.vehiculo_activo = 1
    db.commit()

    res = client.delete(
        f"/api/v1/missions/{mision_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# Scheduler autónomo GET/PUT /missions/scheduler
# ---------------------------------------------------------------------------


def test_scheduler_status_readable_by_guardia(client, guardia_token):
    res = client.get(
        "/api/v1/missions/scheduler",
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "enabled" in body
    assert "programmed_count" in body


def test_scheduler_toggle_requires_admin(client, guardia_token):
    res = client.put(
        "/api/v1/missions/scheduler",
        json={"enabled": False},
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert res.status_code == 403


def test_scheduler_toggle_admin(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.put("/api/v1/missions/scheduler", json={"enabled": True}, headers=headers)
    assert res.status_code == 200
    assert res.json()["enabled"] is True

    status_res = client.get("/api/v1/missions/scheduler", headers=headers)
    assert status_res.json()["enabled"] is True

    res = client.put("/api/v1/missions/scheduler", json={"enabled": False}, headers=headers)
    assert res.status_code == 200
    assert res.json()["enabled"] is False


# ---------------------------------------------------------------------------
# Zonas de exclusión: CRUD y reglas de bloqueo
# ---------------------------------------------------------------------------


def test_exclusion_zone_crud(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    zona = _create_zone(
        client,
        admin_token,
        clasificacion="advertencia",
        motivo="Obra en curso",
        descripcion="Grúa temporal",
        codigo_badge="OBRAS",
        altitud_max_m=40.0,
    )
    assert zona["clasificacion"] == "advertencia"
    assert zona["motivo"] == "Obra en curso"
    assert zona["codigo_badge"] == "OBRAS"
    assert zona["altitud_max_m"] == 40.0
    assert zona["activa"] is True

    lista = client.get("/api/v1/exclusion-zones/", headers=headers)
    assert any(z["id"] == zona["id"] for z in lista.json())

    res = client.put(
        f"/api/v1/exclusion-zones/{zona['id']}",
        json={"nombre": "Zona Rectoría Norte", "clasificacion": "restringida"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["nombre"] == "Zona Rectoría Norte"
    assert res.json()["clasificacion"] == "restringida"

    toggled = client.patch(f"/api/v1/exclusion-zones/{zona['id']}/toggle", headers=headers)
    assert toggled.status_code == 200
    assert toggled.json()["activa"] is False

    deleted = client.delete(f"/api/v1/exclusion-zones/{zona['id']}", headers=headers)
    assert deleted.status_code == 204


def test_exclusion_zone_write_forbidden_for_guardia(client, guardia_token):
    headers = {"Authorization": f"Bearer {guardia_token}"}
    res = client.post("/api/v1/exclusion-zones/", json=ZONA_CAMPUS, headers=headers)
    assert res.status_code == 403
    res = client.put("/api/v1/exclusion-zones/1", json={"nombre": "X zona"}, headers=headers)
    assert res.status_code == 403
    res = client.patch("/api/v1/exclusion-zones/1/toggle", headers=headers)
    assert res.status_code == 403
    res = client.delete("/api/v1/exclusion-zones/1", headers=headers)
    assert res.status_code == 403


def test_restricted_zone_blocks_mission_creation(client, admin_token):
    _create_zone(client, admin_token, clasificacion="restringida")
    # WP_A/WP_B caen dentro del rectángulo de la zona
    r = _create_mission(client, admin_token)
    assert r.status_code == 400
    assert "exclusión" in r.json()["detail"].lower() or "restringida" in r.json()["detail"].lower()


def test_warning_zone_does_not_block(client, admin_token):
    _create_zone(client, admin_token, clasificacion="advertencia")
    r = _create_mission(client, admin_token)
    assert r.status_code == 201, r.text


def test_altitude_ceiling_only_blocks_below(client, admin_token):
    """Una zona con altitud_max_m bloquea solo waypoints internos por debajo
    del tope de estructura; volar por encima sigue siendo válido."""
    _create_zone(client, admin_token, clasificacion="restringida", altitud_max_m=30.0)

    bajo = _create_mission(client, admin_token)  # altitud 20 m < tope 30 m
    assert bajo.status_code == 400

    arriba = _create_mission(
        client,
        admin_token,
        waypoints=[{**WP_A, "altitud_metros": 60.0}, {**WP_B, "altitud_metros": 60.0}],
    )
    assert arriba.status_code == 201, arriba.text


def test_evitacion_exclusion_false_bypasses_check(client, admin_token):
    _create_zone(client, admin_token, clasificacion="restringida")
    r = _create_mission(client, admin_token, evitacion_exclusion=False)
    assert r.status_code == 201, r.text


def test_inactive_zone_does_not_block(client, admin_token):
    _create_zone(client, admin_token, activa=False)
    r = _create_mission(client, admin_token)
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# Geocercas operativas: edición
# ---------------------------------------------------------------------------


def test_update_geofence(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    fence = client.post(
        "/api/v1/geofences/",
        json={
            "nombre": "Campus Norte",
            "tipo": "CIRCULAR",
            "centro_lat": 20.70428,
            "centro_lon": -100.44358,
            "radio_metros": 300.0,
            "motivo": "Perímetro inicial",
        },
        headers=headers,
    )
    assert fence.status_code == 201, fence.text
    fence_id = fence.json()["id"]

    res = client.put(
        f"/api/v1/geofences/{fence_id}",
        json={"nombre": "Campus Norte Ampliado", "motivo": "Ampliación", "radio_metros": 450.0},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["nombre"] == "Campus Norte Ampliado"
    assert body["motivo"] == "Ampliación"
    assert body["radio_metros"] == 450.0


def test_update_geofence_guardia_forbidden(client, admin_token, guardia_token):
    fence = client.post(
        "/api/v1/geofences/",
        json={
            "nombre": "Campus Sur",
            "tipo": "CIRCULAR",
            "centro_lat": 20.70428,
            "centro_lon": -100.44358,
            "radio_metros": 200.0,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    res = client.put(
        f"/api/v1/geofences/{fence['id']}",
        json={"motivo": "intento"},
        headers={"Authorization": f"Bearer {guardia_token}"},
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Servicio de geocercas: evaluación directa de la ruta
# ---------------------------------------------------------------------------


def test_evaluate_route_against_zones(db):
    """Contrato legacy: zonas sin clasificacion se comportan como restringida;
    las de advertencia solo generan avisos."""
    zona_legacy = ZonaExclusion(
        nombre="Zona sin clasificar",
        lat_min=20.7040,
        lat_max=20.7050,
        lon_min=-100.4440,
        lon_max=-100.4430,
        activa=True,
    )
    zona_aviso = ZonaExclusion(
        nombre="Zona de aviso",
        lat_min=20.7060,
        lat_max=20.7070,
        lon_min=-100.4440,
        lon_max=-100.4430,
        activa=True,
        clasificacion="advertencia",
    )
    db.add_all([zona_legacy, zona_aviso])
    db.commit()

    # La zona legacy (sin clasificacion) bloquea como restringida.
    error, _warnings = evaluate_route_against_zones(
        db,
        [{"latitud": 20.7045, "longitud": -100.4435, "altitud_metros": 15.0}],
    )
    assert error is not None and "exclusión" in error

    # Una ruta que solo cruza la zona de advertencia no bloquea pero avisa.
    error, warnings = evaluate_route_against_zones(
        db,
        [
            {"latitud": 20.7065, "longitud": -100.4435, "altitud_metros": 15.0},
            {"latitud": 20.7080, "longitud": -100.4435, "altitud_metros": 15.0},
        ],
    )
    assert error is None
    assert any("advertencia" in w for w in warnings)


# ---------------------------------------------------------------------------
# Servicio de misiones: ejecutado_por, hover, recurrencia
# ---------------------------------------------------------------------------


@pytest.fixture()
def mission_exec(db, admin_user):
    """MissionService con dron falso y hilo diferido, igual que test_mission_execution."""
    drone = FakeDrone()
    service = MissionService(TestingSessionLocal, drone, DeferredThread)

    def create(**overrides):
        fields = {"nombre": "Ruta agente 3", "creado_por": admin_user.id}
        fields.update(overrides)
        mission = Mision(**fields)
        mission.waypoints = [
            Ruta(orden_waypoint=1, latitud=20.7043, longitud=-100.4435, altitud_metros=15.0),
            Ruta(orden_waypoint=2, latitud=20.7048, longitud=-100.4432, altitud_metros=15.0),
        ]
        db.add(mission)
        db.commit()
        return mission.id

    def read(mision_id):
        db.expire_all()
        return db.get(Mision, mision_id)

    return SimpleNamespace(
        service=service, drone=drone, create=create, read=read, admin_id=admin_user.id
    )


def test_start_records_ejecutado_por(mission_exec):
    mision_id = mission_exec.create()
    mission_exec.service.start(mision_id, ejecutado_por=mission_exec.admin_id)
    mision = mission_exec.read(mision_id)
    assert mision.estado == "EN_CURSO"
    assert mision.ejecutado_por == mission_exec.admin_id
    mission_exec.service.worker.run()


def test_start_rejects_route_through_restricted_zone(mission_exec, db):
    db.add(
        ZonaExclusion(
            nombre="Bloqueo en inicio",
            lat_min=20.7040,
            lat_max=20.7050,
            lon_min=-100.4440,
            lon_max=-100.4430,
            activa=True,
            clasificacion="restringida",
        )
    )
    db.commit()
    mision_id = mission_exec.create()
    with pytest.raises(MissionError) as exc:
        mission_exec.service.start(mision_id)
    assert exc.value.status_code == 422
    assert mission_exec.read(mision_id).estado == "PROGRAMADA"


def test_start_bypasses_zone_when_evitacion_disabled(mission_exec, db):
    db.add(
        ZonaExclusion(
            nombre="Bloqueo omitido",
            lat_min=20.7040,
            lat_max=20.7050,
            lon_min=-100.4440,
            lon_max=-100.4430,
            activa=True,
            clasificacion="restringida",
        )
    )
    db.commit()
    mision_id = mission_exec.create(evitacion_exclusion=False)
    mission_exec.service.start(mision_id)
    assert mission_exec.read(mision_id).estado == "EN_CURSO"
    mission_exec.service.worker.run()


def test_finished_recurrent_mission_clones_next_run(mission_exec, db):
    """Una misión recurrente FINALIZADA genera una nueva PROGRAMADA en el
    siguiente día válido, copiando waypoints y hover_segundos."""
    lunes = datetime(2026, 1, 5, 10, 0, 0)  # 2026-01-05 = lunes
    assert lunes.weekday() == 0

    fields = {
        "nombre": "Patrulla semanal",
        "creado_por": mission_exec.admin_id,
        "horario_inicio_programado": lunes,
        "horario_fin_programado": lunes + timedelta(minutes=30),
        "duracion_estimada_min": 30,
        "helipuerto_salida": "Helipuerto Norte",
        "es_recurrente": True,
        "dias_semana_json": json.dumps(["lun", "vie"]),
    }
    mission = Mision(**fields)
    mission.waypoints = [
        Ruta(orden_waypoint=1, latitud=20.7043, longitud=-100.4435, altitud_metros=15.0,
             hover_segundos=8.0),
        Ruta(orden_waypoint=2, latitud=20.7048, longitud=-100.4432, altitud_metros=15.0),
    ]
    db.add(mission)
    db.commit()
    mision_id = mission.id

    mission_exec.service.start(mision_id)
    mission_exec.service.worker.run()
    assert mission_exec.read(mision_id).estado == "FINALIZADA"

    db.expire_all()
    clon = (
        db.query(Mision)
        .filter(Mision.id != mision_id, Mision.estado == "PROGRAMADA")
        .first()
    )
    assert clon is not None
    assert clon.nombre == "Patrulla semanal"
    assert clon.es_recurrente is True
    assert clon.dias_semana == ["lun", "vie"]
    assert clon.helipuerto_salida == "Helipuerto Norte"
    # La base (enero 2026) ya quedó en el pasado: la recurrencia se ancla a
    # ahora conservando la hora programada (10:00) en el próximo lun/vie.
    assert clon.horario_inicio_programado > datetime.now()
    assert clon.horario_inicio_programado.weekday() in (0, 4)
    assert clon.horario_inicio_programado.time() == lunes.time()
    assert len(clon.waypoints) == 2
    assert clon.waypoints[0].hover_segundos == 8.0
