"""
Suite integral de pruebas del Agente 4:
- Alertas enriquecidas sin N+1, filtro ?tipo=, estado de lectura/descarte por usuario (AlertaUsuario) y read-all.
- Ciclo completo de Eventos (PENDIENTE -> EN_REVISION -> RESUELTO con notas_resolucion y Auditoria).
- Difuminado automático de rostros (FramePipeline.blur_faces), captura de evidencia autenticada
  (POST /video/capture-evidence), servido autenticado sin 404 (GET /detections/{id}/frame),
  umbral IA dinámico (AjustesOperativos) y detección diurna en ZonaExclusion (PERSONA_ZONA_RESTRINGIDA).
- Grabaciones con retención dinámica, HTTP Range (206 Partial Content), descarga auditada y purga
  normativa preservando el registro + checksum SHA-256 (purgado=True -> 410 en stream).
- Bitácora de vuelos inmutable con cadena criptográfica SHA-256 (prev_hash + hash_sha256) y
  endpoint de verificación GET /flight-logs/{id}/verify.
"""

from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from app.models.audit import Auditoria
from app.models.flight_log import GENESIS_HASH, BitacoraVuelo
from app.models.geofence import ZonaExclusion
from app.models.recording import Grabacion
from app.models.setting import AjustesOperativos
from app.services.purge_job import purge_expired_recordings
from app.services.video_stream_service import video_stream_service
from app.vision.pipeline import FramePipeline


def _ingest_detection(client, **overrides):
    payload = {
        "tipo": "HUMO",
        "nivel_confianza": 0.91,
        "latitud": 20.7042,
        "longitud": -100.4438,
        "altitud_metros": 42.5,
        "timestamp": "2026-11-20T22:30:00",
    }
    payload.update(overrides)
    res = client.post("/api/v1/detections/ingest", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_per_user_alert_read_dismiss_and_filters(client, admin_token, guardia_token):
    """Guardia y Admin tienen estado independiente de lectura y descarte; GET /alerts/ incluye evento."""
    _ingest_detection(client, tipo="HUMO", nivel_confianza=0.93)
    _ingest_detection(client, tipo="PERSONA", nivel_confianza=0.88, timestamp="2026-11-20T23:15:00")

    g_headers = {"Authorization": f"Bearer {guardia_token}"}
    a_headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. GET /alerts/ devuelve alertas con evento y detecciones embebidas (cero N+1)
    g_list = client.get("/api/v1/alerts/", headers=g_headers)
    assert g_list.status_code == 200
    alerts = g_list.json()
    assert len(alerts) == 2
    assert all(a["evento"] is not None for a in alerts)
    assert all(len(a["evento"]["detecciones"]) >= 1 for a in alerts)
    assert all(a["leida_por_usuario"] is False for a in alerts)

    # 2. Filtro ?tipo=HUMO y ?tipo=INTRUSO
    humo_only = client.get("/api/v1/alerts/?tipo=HUMO", headers=g_headers).json()
    assert len(humo_only) == 1
    assert humo_only[0]["evento"]["tipo"] == "HUMO_DETECTADO"

    intruso_only = client.get("/api/v1/alerts/?tipo=INTRUSO", headers=g_headers).json()
    assert len(intruso_only) == 1
    assert intruso_only[0]["evento"]["tipo"] == "PERSONA_NOCTURNA"

    target_alert_id = humo_only[0]["id"]

    # 3. Guardia marca como leída -> para Guardia es True, para Admin sigue False
    mark_res = client.patch(f"/api/v1/alerts/{target_alert_id}/read", headers=g_headers)
    assert mark_res.status_code == 200
    assert mark_res.json()["leida_por_usuario"] is True

    admin_alerts = client.get("/api/v1/alerts/", headers=a_headers).json()
    admin_target = next(a for a in admin_alerts if a["id"] == target_alert_id)
    assert admin_target["leida_por_usuario"] is False

    # 4. Guardia descarta una alerta -> desaparece para Guardia (salvo include_dismissed=true), Admin aún la ve
    dismiss_res = client.patch(f"/api/v1/alerts/{target_alert_id}/dismiss", headers=g_headers)
    assert dismiss_res.status_code == 200
    assert dismiss_res.json()["descartada"] is True

    g_visible = client.get("/api/v1/alerts/", headers=g_headers).json()
    assert len(g_visible) == 1
    g_all = client.get("/api/v1/alerts/?include_dismissed=true", headers=g_headers).json()
    assert len(g_all) == 2

    admin_still_sees = client.get("/api/v1/alerts/", headers=a_headers).json()
    assert len(admin_still_sees) == 2

    # 5. Admin marca todas como vistas con POST /alerts/read-all
    read_all = client.post("/api/v1/alerts/read-all", headers=a_headers)
    assert read_all.status_code == 200
    assert read_all.json()["updated"] == 2

    admin_after = client.get("/api/v1/alerts/", headers=a_headers).json()
    assert all(a["leida_por_usuario"] is True for a in admin_after)


def test_event_dispatch_and_resolution_workflow(client, db, guardia_token, guardia_user, admin_token, admin_user):
    """Flujo completo PENDIENTE -> EN_REVISION -> RESUELTO con notas y auditoría."""
    _ingest_detection(client, tipo="HUMO", nivel_confianza=0.95)
    g_headers = {"Authorization": f"Bearer {guardia_token}"}
    a_headers = {"Authorization": f"Bearer {admin_token}"}

    alerts = client.get("/api/v1/alerts/", headers=g_headers).json()
    evento_id = alerts[0]["evento_id"]

    # 1. Guardia despacha incidente (EN_REVISION)
    dispatch_res = client.patch(
        f"/api/v1/events/{evento_id}/status",
        json={"estado": "EN_REVISION"},
        headers=g_headers,
    )
    assert dispatch_res.status_code == 200
    dispatched = dispatch_res.json()
    assert dispatched["estado"] == "EN_REVISION"
    assert dispatched["atendido_por_id"] == guardia_user.id
    assert dispatched["despachado_at"] is not None

    # 2. Admin cierra incidente con notas_resolucion (RESUELTO)
    resolve_res = client.patch(
        f"/api/v1/events/{evento_id}/status",
        json={"estado": "RESUELTO", "notas_resolucion": "Conato controlado por brigada interna FIF."},
        headers=a_headers,
    )
    assert resolve_res.status_code == 200
    resolved = resolve_res.json()
    assert resolved["estado"] == "RESUELTO"
    assert resolved["resuelto_por_id"] == admin_user.id
    assert resolved["resuelto_at"] is not None
    assert "brigada interna FIF" in resolved["notas_resolucion"]

    # Verificar entradas en Auditoria
    acciones = [a.accion for a in db.query(Auditoria).all()]
    assert "DESPACHAR_GUARDIA_EVENTO" in acciones
    assert "RESOLVER_EVENTO" in acciones


def test_face_blur_evidence_capture_and_detection_frame_serving(
    client, guardia_token, tmp_path: Path, monkeypatch
):
    """Difuminado de rostros, POST /video/capture-evidence autenticado y GET /detections/{id}/frame sin 404."""
    from app.api.v1.endpoints import video as video_ep

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(video_ep, "EVIDENCE_FRAMES_DIR", frames_dir)

    # 1. Verificar que FramePipeline.blur_faces difumina efectivamente la región indicada
    img = np.zeros((120, 120, 3), dtype=np.uint8)
    cv2.rectangle(img, (35, 35), (65, 65), (255, 255, 255), -1)
    cv2.line(img, (40, 40), (60, 60), (0, 0, 0), 3)
    blurred = FramePipeline.blur_faces(img, extra_boxes=[(30, 30, 70, 70)])
    assert not np.array_equal(img[35:65, 35:65], blurred[35:65, 35:65])

    ok, encoded_jpeg = cv2.imencode(".jpg", img)
    assert ok
    video_stream_service.publish_jpeg(encoded_jpeg.tobytes(), width=120, height=120)

    # 2. POST /video/capture-evidence sin token devuelve 401
    unauth = client.post("/api/v1/video/capture-evidence")
    assert unauth.status_code == 401

    # 3. POST /video/capture-evidence con token de Guardia guarda JPEG + SHA-256 + Deteccion
    g_headers = {"Authorization": f"Bearer {guardia_token}"}
    cap_res = client.post(
        "/api/v1/video/capture-evidence?blur_faces=true",
        headers=g_headers,
    )
    assert cap_res.status_code == 201, cap_res.text
    cap_data = cap_res.json()
    assert len(cap_data["checksum_sha256"]) == 64
    det_id = cap_data["id"]

    # 4. GET /detections/{id}/frame sirve el JPEG autenticado (por header o ?token=) y rechaza sin token
    no_tok = client.get(f"/api/v1/detections/{det_id}/frame")
    assert no_tok.status_code == 401

    frame_res = client.get(f"/api/v1/detections/{det_id}/frame?token={guardia_token}")
    assert frame_res.status_code == 200
    assert frame_res.headers["content-type"] == "image/jpeg"
    assert frame_res.headers["x-evidence-sha256"] == cap_data["checksum_sha256"]
    assert frame_res.content.startswith(b"\xff\xd8")


def test_dynamic_ai_sensitivity_and_daytime_restricted_zone_alert(client, db, guardia_token):
    """Umbral dinámico AjustesOperativos.ai_sensitivity_id y alerta diurna en ZonaExclusion."""
    # Configurar sensibilidad estricta "98" -> umbral 0.85
    db.add(
        AjustesOperativos(
            transmission_quality_id="fhd-60",
            retention_days=30,
            ai_sensitivity_id="98",
            critical_push_enabled=True,
        )
    )
    # Crear zona restringida activa
    db.add(
        ZonaExclusion(
            nombre="Subestación Eléctrica FIF",
            lat_min=20.7000,
            lat_max=20.7050,
            lon_min=-100.4460,
            lon_max=-100.4400,
            activa=True,
        )
    )
    db.commit()

    # Detección de humo con 0.80 (< 0.85) NO debe disparar evento bajo perfil "98"
    _ingest_detection(client, tipo="HUMO", nivel_confianza=0.80, timestamp="2026-11-20T14:00:00")
    g_headers = {"Authorization": f"Bearer {guardia_token}"}
    assert client.get("/api/v1/alerts/", headers=g_headers).json() == []

    # Persona de DÍA (14:10 hrs) DENTRO de la zona restringida con confianza 0.90 (>= 0.85) SÍ dispara alerta
    _ingest_detection(
        client,
        tipo="PERSONA",
        nivel_confianza=0.90,
        latitud=20.7025,
        longitud=-100.4430,
        timestamp="2026-11-20T14:10:00",
    )
    alerts = client.get("/api/v1/alerts/", headers=g_headers).json()
    assert len(alerts) == 1
    assert alerts[0]["evento"]["tipo"] == "PERSONA_ZONA_RESTRINGIDA"
    assert "Subestación Eléctrica FIF" in alerts[0]["titulo"]


def test_recordings_dynamic_retention_http_range_audit_and_normative_purge(
    client, db, admin_token, guardia_token, tmp_path: Path, monkeypatch
):
    """Retención dinámica, HTTP 206 Range, descarga auditada y purga preservando SHA-256."""
    from app.api.v1.endpoints import recordings as rec_ep

    storage_dir = tmp_path / "recordings"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rec_ep, "STORAGE_DIR", str(storage_dir))

    # Ajustar retención operativa a 60 días
    db.add(
        AjustesOperativos(
            transmission_quality_id="hd-30",
            retention_days=60,
            ai_sensitivity_id="95",
            critical_push_enabled=True,
        )
    )
    db.commit()

    raw_mp4 = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_MP4_PAYLOAD_TEST"
    up_res = client.post(
        "/api/v1/recordings/upload",
        data={"vuelo_id": "77", "duracion_segundos": "12"},
        files={"file": ("segmento.mp4", raw_mp4, "video/mp4")},
    )
    assert up_res.status_code == 201, up_res.text
    uploaded = up_res.json()
    rec_id = uploaded["id"]
    expected_sha = uploaded["checksum_sha256"]
    assert uploaded["dias_restantes_purga"] >= 59
    assert uploaded["purgado"] is False

    # 1. Stream con Range: bytes=0-9 y autenticación vía ?token= (como <video src="...?token=...">)
    range_res = client.get(
        f"/api/v1/recordings/{rec_id}/stream?token={guardia_token}",
        headers={"Range": "bytes=0-9"},
    )
    assert range_res.status_code == 206
    assert range_res.content == b"0123456789"
    assert range_res.headers["content-range"] == f"bytes 0-9/{len(raw_mp4)}"
    assert range_res.headers["accept-ranges"] == "bytes"

    # 2. Descarga por ADMIN registra DESCARGAR_GRABACION en Auditoria
    dl_res = client.get(
        f"/api/v1/recordings/{rec_id}/download",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert dl_res.status_code == 200
    assert dl_res.content == raw_mp4
    assert db.query(Auditoria).filter(Auditoria.accion == "DESCARGAR_GRABACION").count() == 1

    # 3. Forzar expiración y ejecutar purge_expired_recordings(db): borra .enc pero conserva fila + SHA-256
    rec_row = db.query(Grabacion).filter(Grabacion.id == rec_id).first()
    enc_path = Path(rec_row.ruta_archivo)
    assert enc_path.exists()
    rec_row.fecha_purga = datetime.utcnow() - timedelta(days=1)
    db.commit()

    purged_count = purge_expired_recordings(db)
    assert purged_count == 1
    assert not enc_path.exists()

    db.refresh(rec_row)
    assert rec_row.purgado is True
    assert rec_row.checksum_sha256 == expected_sha

    # Stream de grabación purgada devuelve 410 Gone
    gone_res = client.get(f"/api/v1/recordings/{rec_id}/stream?token={admin_token}")
    assert gone_res.status_code == 410


def test_immutable_flight_log_hash_chain_and_verification_endpoint(client, db, admin_user, guardia_token):
    """BitacoraVuelo sella prev_hash + hash_sha256 en cadena y GET /flight-logs/{id}/verify lo comprueba."""
    log1 = BitacoraVuelo(
        vuelo_id=101,
        operador_id=admin_user.id,
        fecha_inicio=datetime(2026, 11, 20, 10, 0, 0),
        fecha_fin=datetime(2026, 11, 20, 10, 15, 0),
        duracion_segundos=900,
        estado_final="FINALIZADA",
        incidentes="Patrullaje matutino sin novedad",
        resumen_telemetria={"bateria_min_pct": 64, "altitud_max_m": 45.0},
    )
    db.add(log1)
    db.commit()
    db.refresh(log1)

    log2 = BitacoraVuelo(
        vuelo_id=102,
        operador_id=admin_user.id,
        fecha_inicio=datetime(2026, 11, 20, 22, 0, 0),
        fecha_fin=datetime(2026, 11, 20, 22, 20, 0),
        duracion_segundos=1200,
        estado_final="FINALIZADA",
        incidentes="Ronda nocturna con 1 alerta",
        resumen_telemetria={"bateria_min_pct": 52, "altitud_max_m": 50.0},
    )
    db.add(log2)
    db.commit()
    db.refresh(log2)

    assert log1.prev_hash == GENESIS_HASH
    assert len(log1.hash_sha256) == 64
    assert log2.prev_hash == log1.hash_sha256
    assert len(log2.hash_sha256) == 64
    assert log2.hash_sha256 != log1.hash_sha256

    headers = {"Authorization": f"Bearer {guardia_token}"}

    # Listado enriquecido con nombre/email/rol del operador
    logs_res = client.get("/api/v1/flight-logs/", headers=headers)
    assert logs_res.status_code == 200
    listed = logs_res.json()
    assert len(listed) == 2
    assert listed[0]["operador_nombre"] == admin_user.nombre
    assert listed[0]["operador_rol"] == "ADMIN"

    # Verificación criptográfica de ambos eslabones en el servidor
    v1 = client.get(f"/api/v1/flight-logs/{log1.id}/verify", headers=headers)
    assert v1.status_code == 200
    assert v1.json()["hash_valid"] is True
    assert v1.json()["chain_valid"] is True

    v2 = client.get(f"/api/v1/flight-logs/{log2.id}/verify", headers=headers)
    assert v2.status_code == 200
    v2_body = v2.json()
    assert v2_body["hash_valid"] is True
    assert v2_body["chain_valid"] is True
    assert v2_body["prev_hash"] == log1.hash_sha256
