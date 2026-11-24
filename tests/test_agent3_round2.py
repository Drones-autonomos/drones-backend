"""Ronda 2 — Agente 3: bitácora automática, presets para GUARDIA, scheduler
persistente, política DELETE con bitácora, evitación efectiva en PUT,
auditoría de mutaciones y POST /geofences/validate-route batch.

Cubre:
- Sellado automático de BitacoraVuelo (hash chain) en FINALIZADA/CANCELADA/
  FALLIDA con resumen de telemetría e incidentes, sin duplicar registros.
- Recurrencia anclada al futuro cuando la base ya quedó atrás, y clonación
  también tras FALLIDA.
- POST /missions/start-preset/{key} para GUARDIA/ADMIN: 404 preset
  desconocido, 400 por zona de exclusión, misión persistida + auditoría.
- DELETE /missions/{id}: FINALIZADA y cualquier misión con bitácora sellada
  quedan bloqueadas (archivo histórico); la telemetría se desvincula.
- PUT /missions/{id}: la evitación efectiva combina payload + persistido.
- PUT /missions/scheduler persiste en AjustesOperativos.scheduler_enabled.
- Auditoría (CREAR_MISION, ELIMINAR_MISION, INICIAR_PATRULLAJE_PRESET,
  TOGGLE_SCHEDULER, CREAR_GEOCERCA).
- /geofences/validate-route: violaciones 'geocerca'|'exclusion'|'advertencia'
  con waypoint_index 1-based y tope de estructura sobrevolable.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import missions as missions_endpoint
from app.main import app
from app.models.audit import Auditoria
from app.models.detection import Deteccion
from app.models.flight_log import GENESIS_HASH, BitacoraVuelo
from app.models.geofence import Geocerca, ZonaExclusion
from app.models.mission import Mision, Ruta
from app.models.setting import AjustesOperativos
from app.models.telemetry import TelemetriaVuelo
from app.services.mission_service import MissionService, get_mission_service
from tests.conftest import TestingSessionLocal
from tests.test_mission_execution import DeferredThread, FakeDrone

# ---------------------------------------------------------------------------
# Payloads y helpers
# ---------------------------------------------------------------------------

WP_A = {"orden_waypoint": 1, "latitud": 20.7043, "longitud": -100.4435, "altitud_metros": 20.0}
WP_B = {"orden_waypoint": 2, "latitud": 20.7048, "longitud": -100.4432, "altitud_metros": 20.0}

MISSION_MIN = {"nombre": "Patrulla R2", "waypoints": [WP_A, WP_B]}

# Rectángulo que cubre los waypoints de prueba → bloqueo de exclusión.
ZONA_BLOQUEO = {
    "nombre": "Bloqueo R2",
    "lat_min": 20.7040,
    "lat_max": 20.7050,
    "lon_min": -100.4440,
    "lon_max": -100.4430,
    "clasificacion": "restringida",
    "activa": True,
}


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _create_mission(client, token, **overrides):
    return client.post(
        "/api/v1/missions/",
        json={**MISSION_MIN, **overrides},
        headers=_headers(token),
    )


def _new_mision(db, creado_por, **overrides):
    fields = {"nombre": "Misión R2", "creado_por": creado_por}
    fields.update(overrides)
    mission = Mision(**fields)
    mission.waypoints = [
        Ruta(orden_waypoint=1, latitud=20.7043, longitud=-100.4435, altitud_metros=15.0),
        Ruta(orden_waypoint=2, latitud=20.7048, longitud=-100.4432, altitud_metros=15.0),
    ]
    db.add(mission)
    db.commit()
    return mission.id


@pytest.fixture()
def mission_svc(db, admin_user):
    """MissionService con dron falso e hilo diferido para sellar bitácoras."""
    service = MissionService(TestingSessionLocal, FakeDrone(), DeferredThread)
    return SimpleNamespace(
        service=service,
        admin_id=admin_user.id,
        create=lambda **kw: _new_mision(db, admin_user.id, **kw),
        read=lambda mid: (db.expire_all(), db.get(Mision, mid))[1],
    )


def _injected_service():
    # El fixture `client` registra un lambda que devuelve la MISMA instancia.
    factory = app.dependency_overrides.get(get_mission_service)
    return factory() if factory else None


def _audits(db, accion):
    return db.query(Auditoria).filter(Auditoria.accion == accion).all()


# ---------------------------------------------------------------------------
# Bitácora automática en estados terminales
# ---------------------------------------------------------------------------


def test_finish_finalizada_sella_bitacora(mission_svc, db):
    """_finish(FINALIZADA) inserta BitacoraVuelo encadenada (prev_hash = GENESIS)
    con resumen de telemetría e incidentes agregados de detecciones."""
    mision_id = mission_svc.create(estado="EN_CURSO", vehiculo_activo=1)
    db.add_all(
        [
            TelemetriaVuelo(mision_id=mision_id, altitud_metros=12.0, bateria_porcentaje=88.0),
            TelemetriaVuelo(mision_id=mision_id, altitud_metros=31.5, bateria_porcentaje=64.0),
            Deteccion(vuelo_id=mision_id, tipo="PERSONA", nivel_confianza=0.9,
                      latitud=20.7044, longitud=-100.4434),
            Deteccion(vuelo_id=mision_id, tipo="PERSONA", nivel_confianza=0.7,
                      latitud=20.7046, longitud=-100.4433),
            Deteccion(vuelo_id=mision_id, tipo="HUMO", nivel_confianza=0.5,
                      latitud=20.7047, longitud=-100.4432),
        ]
    )
    db.commit()

    mission_svc.service._finish(mision_id, "FINALIZADA", grounded=True)

    logs = db.query(BitacoraVuelo).filter(BitacoraVuelo.vuelo_id == mision_id).all()
    assert len(logs) == 1
    log = logs[0]
    assert log.estado_final == "FINALIZADA"
    assert log.prev_hash == GENESIS_HASH
    assert log.hash_sha256 and len(log.hash_sha256) == 64
    assert log.operador_id == mission_svc.admin_id
    assert log.resumen_telemetria["muestras"] == 2
    assert log.resumen_telemetria["altitud_max_m"] == 31.5
    assert log.resumen_telemetria["bateria_min_pct"] == 64.0
    assert "3 detecciones" in log.incidentes
    assert "PERSONA: 2" in log.incidentes
    assert "HUMO: 1" in log.incidentes

    # Idempotente: un segundo sellado no duplica el registro.
    mission_svc.service._finish(mision_id, "FINALIZADA", grounded=True)
    assert db.query(BitacoraVuelo).filter(BitacoraVuelo.vuelo_id == mision_id).count() == 1


def test_finish_fallida_sella_bitacora_con_error(mission_svc, db):
    mision_id = mission_svc.create(estado="EN_CURSO", vehiculo_activo=1)
    mission_svc.service._finish(
        mision_id, "FALLIDA", "Pérdida de enlace en waypoint 3", grounded=True
    )
    log = db.query(BitacoraVuelo).filter(BitacoraVuelo.vuelo_id == mision_id).one()
    assert log.estado_final == "FALLIDA"
    assert "Pérdida de enlace" in log.incidentes


def test_finish_cancelada_sella_bitacora(mission_svc, db):
    mision_id = mission_svc.create(estado="EN_CURSO", vehiculo_activo=1)
    mission_svc.service._finish(mision_id, "CANCELADA", grounded=True)
    assert (
        db.query(BitacoraVuelo).filter(BitacoraVuelo.vuelo_id == mision_id).count() == 1
    )


def test_bitacora_es_inmutable(mission_svc, db):
    """BitacoraVuelo prohíbe UPDATE/DELETE: la misión sellada es archivo histórico."""
    mision_id = mission_svc.create(estado="EN_CURSO", vehiculo_activo=1)
    mission_svc.service._finish(mision_id, "FINALIZADA", grounded=True)
    log = db.query(BitacoraVuelo).filter(BitacoraVuelo.vuelo_id == mision_id).one()
    log.estado_final = "ALTERADA"
    with pytest.raises(ValueError, match="inmutable"):
        db.commit()
    db.rollback()


def test_confirm_landed_sella_bitacora_tras_interrupcion(mission_svc, db):
    """confirm_landed (RECUPERACION → FALLIDA) también sella la bitácora."""
    mision_id = mission_svc.create(estado="RECUPERACION", vehiculo_activo=1)
    mission_svc.service.confirm_landed(mision_id)
    assert mission_svc.read(mision_id).estado == "FALLIDA"
    log = db.query(BitacoraVuelo).filter(BitacoraVuelo.vuelo_id == mision_id).one()
    assert log.estado_final == "FALLIDA"
    assert "interrumpida" in log.incidentes


# ---------------------------------------------------------------------------
# Recurrencia: anclaje al futuro y clonación tras FALLIDA
# ---------------------------------------------------------------------------


def test_recurrencia_no_programa_en_el_pasado(mission_svc, db):
    """Una misión recurrente cuya base ya pasó clona la siguiente corrida en
    una fecha FUTURA (bug corregido en ronda 2)."""
    base = datetime.now() - timedelta(days=40)  # miércoles hace 40 días
    mision_id = mission_svc.create(
        horario_inicio_programado=base,
        horario_fin_programado=base + timedelta(minutes=20),
        es_recurrente=True,
        dias_semana_json=json.dumps(["mie"]),
        estado="EN_CURSO",
        vehiculo_activo=1,
    )
    mission_svc.service._finish(mision_id, "FINALIZADA", grounded=True)

    clon = (
        db.query(Mision)
        .filter(Mision.id != mision_id, Mision.estado == "PROGRAMADA")
        .one()
    )
    assert clon.horario_inicio_programado > datetime.now()
    assert clon.horario_inicio_programado.weekday() == 2  # miércoles
    assert clon.horario_inicio_programado.time() == base.time()
    assert clon.horario_fin_programado > clon.horario_inicio_programado


def test_recurrencia_tambien_tras_fallida(mission_svc, db):
    """La cadena recurrente no se rompe si la corrida falla: FALLIDA clona."""
    base = datetime.now() + timedelta(days=1)
    mision_id = mission_svc.create(
        horario_inicio_programado=base,
        es_recurrente=True,
        dias_semana_json=json.dumps(["lun", "mar", "mie", "jue", "vie", "sab", "dom"]),
        estado="EN_CURSO",
        vehiculo_activo=1,
    )
    mission_svc.service._finish(mision_id, "FALLIDA", "Sin enlace", grounded=True)
    assert (
        db.query(Mision)
        .filter(Mision.id != mision_id, Mision.estado == "PROGRAMADA")
        .count()
        == 1
    )


def test_cancelada_no_clona_recurrencia(mission_svc, db):
    """Cancelar rompe la cadena: CANCELADA no genera la siguiente corrida."""
    base = datetime.now() + timedelta(days=1)
    mision_id = mission_svc.create(
        horario_inicio_programado=base,
        es_recurrente=True,
        dias_semana_json=json.dumps(["lun", "mar", "mie", "jue", "vie", "sab", "dom"]),
        estado="EN_CURSO",
        vehiculo_activo=1,
    )
    mission_svc.service._finish(mision_id, "CANCELADA", grounded=True)
    assert (
        db.query(Mision)
        .filter(Mision.id != mision_id, Mision.estado == "PROGRAMADA")
        .count()
        == 0
    )


# ---------------------------------------------------------------------------
# POST /missions/start-preset/{key}
# ---------------------------------------------------------------------------


def test_start_preset_guardia_crea_e_inicia(client, guardia_token, db, monkeypatch):
    """GUARDIA puede lanzar un preset: la misión se persiste con sus waypoints
    y la acción queda auditada antes del arranque."""
    monkeypatch.setattr(
        missions_endpoint, "validate_operating_window", lambda *_a, **_k: None
    )
    service = _injected_service()
    started = {}

    def fake_start(mision_id, ejecutado_por=None):
        started["args"] = (mision_id, ejecutado_por)
        mision = db.get(Mision, mision_id)
        mision.estado = "EN_CURSO"
        mision.ejecutado_por = ejecutado_por
        mision.vehiculo_activo = 1
        db.commit()

    monkeypatch.setattr(service, "start", fake_start)

    res = client.post(
        "/api/v1/missions/start-preset/clasica", headers=_headers(guardia_token)
    )
    assert res.status_code == 202, res.text
    data = res.json()
    assert data["estado"] == "EN_CURSO"
    assert len(data["waypoints"]) >= 2

    mision = db.get(Mision, data["id"])
    assert mision is not None and mision.es_recurrente is False
    assert mision.evitacion_exclusion is True
    assert started["args"][0] == mision.id

    audits = _audits(db, "INICIAR_PATRULLAJE_PRESET")
    assert len(audits) == 1
    assert "start-preset/clasica" in audits[0].recurso


def test_start_preset_desconocido_404(client, admin_token, db, monkeypatch):
    monkeypatch.setattr(
        missions_endpoint, "validate_operating_window", lambda *_a, **_k: None
    )
    res = client.post(
        "/api/v1/missions/start-preset/no-existe", headers=_headers(admin_token)
    )
    assert res.status_code == 404
    # No se persistió misión fantasma.
    assert db.query(Mision).count() == 0


def test_start_preset_bloqueado_por_zona_exclusion(client, guardia_token, db, monkeypatch):
    """Un preset cuya trayectoria cruza una zona restringida se rechaza 400 y
    no persiste la misión."""
    monkeypatch.setattr(
        missions_endpoint, "validate_operating_window", lambda *_a, **_k: None
    )
    # Rectángulo que cubre todo el campus FI (los presets operan dentro).
    db.add(
        ZonaExclusion(
            nombre="Campus cerrado",
            lat_min=20.60,
            lat_max=20.80,
            lon_min=-100.55,
            lon_max=-100.30,
            activa=True,
            clasificacion="restringida",
        )
    )
    db.commit()
    res = client.post(
        "/api/v1/missions/start-preset/clasica", headers=_headers(guardia_token)
    )
    assert res.status_code == 400
    assert "Campus cerrado" in res.json()["detail"]
    assert db.query(Mision).count() == 0


def test_start_preset_fuera_de_ventana_422(client, guardia_token, monkeypatch):
    """Fuera de la ventana operativa el preset no despega (422)."""

    def _rechaza(_dt):
        raise ValueError("Fuera de la ventana operativa 06:00-23:00")

    monkeypatch.setattr(missions_endpoint, "validate_operating_window", _rechaza)
    res = client.post(
        "/api/v1/missions/start-preset/interior", headers=_headers(guardia_token)
    )
    assert res.status_code == 422


def test_start_preset_requiere_autenticacion(client):
    res = client.post("/api/v1/missions/start-preset/clasica")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# DELETE: política coherente con el archivo histórico
# ---------------------------------------------------------------------------


def test_delete_programada_permitida(client, admin_token):
    """PROGRAMADA sin bitácora es eliminable (204)."""
    r = _create_mission(client, admin_token)
    assert r.status_code == 201, r.text
    mision_id = r.json()["id"]
    res = client.delete(f"/api/v1/missions/{mision_id}", headers=_headers(admin_token))
    assert res.status_code == 204


def test_delete_finalizada_bloqueada(client, admin_token, db):
    r = _create_mission(client, admin_token)
    mision_id = r.json()["id"]
    mision = db.get(Mision, mision_id)
    mision.estado = "FINALIZADA"
    mision.finalizada_at = datetime.now()
    db.commit()
    res = client.delete(f"/api/v1/missions/{mision_id}", headers=_headers(admin_token))
    assert res.status_code == 409
    assert "histórico" in res.json()["detail"]


def test_delete_mision_con_bitacora_bloqueada(client, admin_token, mission_svc, db):
    """FALLIDA normalmente es eliminable, pero con bitácora sellada queda
    protegida como archivo histórico."""
    mision_id = mission_svc.create(estado="EN_CURSO", vehiculo_activo=1)
    mission_svc.service._finish(mision_id, "FALLIDA", "RTL forzado", grounded=True)
    res = client.delete(f"/api/v1/missions/{mision_id}", headers=_headers(admin_token))
    assert res.status_code == 409
    assert "bitácora" in res.json()["detail"].lower()


def test_delete_desvincula_telemetria(client, admin_token, db):
    """Al eliminar una misión PROGRAMADA la telemetría se conserva con
    mision_id=NULL — nunca se borra la evidencia."""
    r = _create_mission(client, admin_token)
    mision_id = r.json()["id"]
    db.add(TelemetriaVuelo(mision_id=mision_id, altitud_metros=10.0))
    db.commit()
    res = client.delete(f"/api/v1/missions/{mision_id}", headers=_headers(admin_token))
    assert res.status_code == 204
    muestras = db.query(TelemetriaVuelo).all()
    assert len(muestras) == 1 and muestras[0].mision_id is None


# ---------------------------------------------------------------------------
# PUT: evitación efectiva (payload + persistido)
# ---------------------------------------------------------------------------


def test_put_respeta_evitacion_persistida(client, admin_token, db):
    """Con evitacion_exclusion=True persistida, actualizar waypoints que
    invaden una zona restringida se rechaza aunque el payload no repita el flag."""
    r = _create_mission(client, admin_token, evitacion_exclusion=True)
    assert r.status_code == 201, r.text
    mision_id = r.json()["id"]
    db.add(ZonaExclusion(**ZONA_BLOQUEO))
    db.commit()
    res = client.put(
        f"/api/v1/missions/{mision_id}",
        json={"waypoints": [WP_A, WP_B]},
        headers=_headers(admin_token),
    )
    assert res.status_code == 400
    assert ZONA_BLOQUEO["nombre"] in res.json()["detail"]


def test_put_permite_desactivar_evitacion(client, admin_token, db):
    """evitacion_exclusion=False en el payload desbloquea los mismos waypoints."""
    r = _create_mission(client, admin_token, evitacion_exclusion=True)
    mision_id = r.json()["id"]
    db.add(ZonaExclusion(**ZONA_BLOQUEO))
    db.commit()
    res = client.put(
        f"/api/v1/missions/{mision_id}",
        json={"evitacion_exclusion": False, "waypoints": [WP_A, WP_B]},
        headers=_headers(admin_token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["evitacion_exclusion"] is False


# ---------------------------------------------------------------------------
# Scheduler persistente + auditoría
# ---------------------------------------------------------------------------


def test_scheduler_persiste_en_ajustes_operativos(client, admin_token, db):
    db.add(AjustesOperativos())
    db.commit()
    res = client.put(
        "/api/v1/missions/scheduler",
        json={"enabled": True},
        headers=_headers(admin_token),
    )
    assert res.status_code == 200
    db.expire_all()
    row = db.query(AjustesOperativos).one()
    assert row.scheduler_enabled is True

    client.put(
        "/api/v1/missions/scheduler",
        json={"enabled": False},
        headers=_headers(admin_token),
    )
    db.expire_all()
    assert db.query(AjustesOperativos).one().scheduler_enabled is False
    assert len(_audits(db, "TOGGLE_SCHEDULER")) == 2


# ---------------------------------------------------------------------------
# Auditoría de mutaciones
# ---------------------------------------------------------------------------


def test_auditoria_crud_mision(client, admin_token, db):
    r = _create_mission(client, admin_token)
    assert r.status_code == 201
    mision_id = r.json()["id"]
    assert len(_audits(db, "CREAR_MISION")) == 1

    res = client.delete(f"/api/v1/missions/{mision_id}", headers=_headers(admin_token))
    assert res.status_code == 204
    eliminar = _audits(db, "ELIMINAR_MISION")
    assert len(eliminar) == 1
    assert f"/missions/{mision_id}" in eliminar[0].recurso


def test_auditoria_crear_geocerca(client, admin_token, db):
    res = client.post(
        "/api/v1/geofences/",
        json={
            "nombre": "Perímetro auditoría",
            "tipo": "CIRCULAR",
            "centro_lat": 20.7044,
            "centro_lon": -100.4434,
            "radio_metros": 500.0,
        },
        headers=_headers(admin_token),
    )
    assert res.status_code == 201, res.text
    assert len(_audits(db, "CREAR_GEOCERCA")) == 1


# ---------------------------------------------------------------------------
# POST /geofences/validate-route
# ---------------------------------------------------------------------------


def _validate_route(client, token, waypoints):
    return client.post(
        "/api/v1/geofences/validate-route",
        json={"waypoints": waypoints},
        headers=_headers(token),
    )


def test_validate_route_sin_geocercas_valida(client, guardia_token):
    """Sin geocercas ni zonas activas, cualquier trayectoria es válida."""
    res = _validate_route(
        client, guardia_token, [{"latitud": 20.0, "longitud": -100.0, "altitud_metros": 20.0}]
    )
    assert res.status_code == 200
    body = res.json()
    assert body["valid"] is True and body["violations"] == []


def test_validate_route_fuera_de_geocerca(client, admin_token, db):
    db.add(
        Geocerca(
            nombre="Campus FI",
            tipo="CIRCULAR",
            activa=True,
            centro_lat=20.7044,
            centro_lon=-100.4434,
            radio_metros=400.0,
        )
    )
    db.commit()
    res = _validate_route(
        client,
        admin_token,
        [
            {"latitud": 20.7044, "longitud": -100.4434, "altitud_metros": 20.0},
            {"latitud": 20.8000, "longitud": -100.9000, "altitud_metros": 20.0},
        ],
    )
    body = res.json()
    assert body["valid"] is False
    geo = [v for v in body["violations"] if v["tipo"] == "geocerca"]
    assert len(geo) == 1 and geo[0]["waypoint_index"] == 2


def test_validate_route_advertencia_no_bloquea(client, admin_token, db):
    """Una zona 'advertencia' cruza la trayectoria: se reporta sin bloquear."""
    db.add(
        ZonaExclusion(
            nombre="Cancha advertencia",
            lat_min=20.7060,
            lat_max=20.7070,
            lon_min=-100.4440,
            lon_max=-100.4430,
            activa=True,
            clasificacion="advertencia",
        )
    )
    db.commit()
    res = _validate_route(
        client,
        admin_token,
        [
            {"latitud": 20.7045, "longitud": -100.4435, "altitud_metros": 20.0},
            {"latitud": 20.7065, "longitud": -100.4435, "altitud_metros": 20.0},
        ],
    )
    body = res.json()
    assert body["valid"] is True
    adv = next(v for v in body["violations"] if v["tipo"] == "advertencia")
    assert "Cancha advertencia" in adv["motivo"]


def test_validate_route_exclusion_bloquea(client, admin_token, db):
    db.add(
        ZonaExclusion(
            nombre="Rectoría restringida",
            lat_min=20.7040,
            lat_max=20.7050,
            lon_min=-100.4440,
            lon_max=-100.4430,
            activa=True,
            clasificacion="restringida",
        )
    )
    db.commit()
    res = _validate_route(
        client,
        admin_token,
        [
            {"latitud": 20.7045, "longitud": -100.4435, "altitud_metros": 20.0},
            {"latitud": 20.7065, "longitud": -100.4435, "altitud_metros": 20.0},
        ],
    )
    body = res.json()
    assert body["valid"] is False
    exc = next(v for v in body["violations"] if v["tipo"] == "exclusion")
    assert "Rectoría restringida" in exc["motivo"]


def test_validate_route_tope_estructura_permite_sobrevuelo(client, admin_token, db):
    """Zona restringida con tope 15 m: volar a 60 m por encima es válido,
    volar a 10 m dentro se bloquea."""
    db.add(
        ZonaExclusion(
            nombre="Arcotecho",
            lat_min=20.7040,
            lat_max=20.7050,
            lon_min=-100.4440,
            lon_max=-100.4430,
            activa=True,
            clasificacion="restringida",
            altitud_max_m=15.0,
        )
    )
    db.commit()
    wps = [
        {"latitud": 20.7045, "longitud": -100.4435, "altitud_metros": 60.0},
        {"latitud": 20.7048, "longitud": -100.4432, "altitud_metros": 60.0},
    ]
    body = _validate_route(client, admin_token, wps).json()
    assert body["valid"] is True

    wps_bajos = [dict(w, altitud_metros=10.0) for w in wps]
    body_bajo = _validate_route(client, admin_token, wps_bajos).json()
    assert body_bajo["valid"] is False
    assert any(v["tipo"] == "exclusion" for v in body_bajo["violations"])
