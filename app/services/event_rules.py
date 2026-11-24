from datetime import datetime

from sqlalchemy.orm import Session

from app.models.alert import Alerta
from app.models.detection import Deteccion
from app.models.event import Evento
from app.models.geofence import ZonaExclusion
from app.models.setting import AjustesOperativos
from app.services.notfication_service import notification_manager

UMBRAL_CONFIANZA = 0.70
AI_SENSITIVITY_THRESHOLDS: dict[str, float] = {
    "90": 0.55,
    "95": 0.70,
    "98": 0.85,
}


def resolve_operator_detection_rules(db: Session) -> tuple[float, bool]:
    """Obtiene el umbral dinámico según ai_sensitivity_id y si critical_push_enabled está activo."""
    try:
        row = db.query(AjustesOperativos).order_by(AjustesOperativos.id.asc()).first()
        if row is None:
            return UMBRAL_CONFIANZA, True
        threshold = AI_SENSITIVITY_THRESHOLDS.get(str(row.ai_sensitivity_id), UMBRAL_CONFIANZA)
        push_enabled = bool(getattr(row, "critical_push_enabled", True))
        return threshold, push_enabled
    except Exception:
        return UMBRAL_CONFIANZA, True


def find_violated_exclusion_zone(db: Session, lat: float, lon: float) -> str | None:
    """Retorna el nombre de la primera ZonaExclusion activa que contiene (lat, lon), o None."""
    try:
        zonas = db.query(ZonaExclusion).filter(ZonaExclusion.activa == True).all()  # noqa: E712
    except Exception:
        return None
    for zona in zonas:
        clasif = str(getattr(zona, "clasificacion", "restringida") or "restringida").lower()
        if clasif == "advertencia":
            continue
        min_lat, max_lat = min(zona.lat_min, zona.lat_max), max(zona.lat_min, zona.lat_max)
        min_lon, max_lon = min(zona.lon_min, zona.lon_max), max(zona.lon_min, zona.lon_max)
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return zona.nombre
    return None


async def evaluate_detection_for_event(db: Session, deteccion: Deteccion) -> Evento | None:
    """
    Evalúa la detección aplicando ajustes dinámicos de sensibilidad IA y zonas restringidas.
    Si califica como incidente, persiste Evento + Alerta y notifica en tiempo real vía WebSocket.
    """
    threshold, push_enabled = resolve_operator_detection_rules(db)
    if deteccion.nivel_confianza < threshold:
        return None

    tipo_normalizado = deteccion.tipo.upper()
    fecha_eval = deteccion.timestamp or datetime.utcnow()
    hora = fecha_eval.hour

    nuevo_evento = None
    titulo_alerta = ""
    mensaje_alerta = ""
    criticidad = "ALTA"

    # 1. Regla de Humo / Conato de incendio (24/7)
    if tipo_normalizado == "HUMO":
        criticidad = "CRITICA"
        titulo_alerta = "ALERTA CRÍTICA: Humo Detectado"
        mensaje_alerta = (
            f"Se detectó humo con {(deteccion.nivel_confianza * 100):.1f}% de confianza "
            f"en coordenadas [{deteccion.latitud}, {deteccion.longitud}]."
        )
        nuevo_evento = Evento(
            tipo="HUMO_DETECTADO",
            nivel_criticidad=criticidad,
            descripcion=mensaje_alerta,
            estado="PENDIENTE",
            created_at=fecha_eval,
        )

    # 2. Regla de Persona: nocturna (21:00–06:00) o diurna dentro de Zona de Exclusión
    elif tipo_normalizado == "PERSONA":
        es_fuera_de_horario = hora >= 21 or hora < 6
        if es_fuera_de_horario:
            criticidad = "ALTA"
            titulo_alerta = "ALERTA DE SEGURIDAD: Persona Fuera de Horario"
            mensaje_alerta = (
                f"Presencia de persona detectada a las {fecha_eval.strftime('%H:%M:%S')} hrs "
                f"con confianza del {(deteccion.nivel_confianza * 100):.1f}%."
            )
            nuevo_evento = Evento(
                tipo="PERSONA_NOCTURNA",
                nivel_criticidad=criticidad,
                descripcion=mensaje_alerta,
                estado="PENDIENTE",
                created_at=fecha_eval,
            )
        else:
            zona_restringida = find_violated_exclusion_zone(
                db,
                float(deteccion.latitud),
                float(deteccion.longitud),
            )
            if zona_restringida:
                criticidad = "ALTA"
                titulo_alerta = f"ALERTA DE SEGURIDAD: Intrusión en {zona_restringida}"
                mensaje_alerta = (
                    f"Persona detectada dentro de la zona restringida '{zona_restringida}' "
                    f"a las {fecha_eval.strftime('%H:%M:%S')} hrs "
                    f"con confianza del {(deteccion.nivel_confianza * 100):.1f}%."
                )
                nuevo_evento = Evento(
                    tipo="PERSONA_ZONA_RESTRINGIDA",
                    nivel_criticidad=criticidad,
                    descripcion=mensaje_alerta,
                    estado="PENDIENTE",
                    created_at=fecha_eval,
                )

    if nuevo_evento:
        db.add(nuevo_evento)
        db.flush()

        deteccion.evento_id = nuevo_evento.id
        db.add(deteccion)

        nueva_alerta = Alerta(
            evento_id=nuevo_evento.id,
            titulo=titulo_alerta,
            mensaje=mensaje_alerta,
            nivel_criticidad=criticidad,
            leida=False,
            destinatario_rol="TODOS",
            timestamp_envio=fecha_eval,
        )
        db.add(nueva_alerta)
        db.flush()

        payload_broadcast = {
            "type": "NEW_ALERT",
            "alerta_id": nueva_alerta.id,
            "evento_id": nuevo_evento.id,
            "titulo": nueva_alerta.titulo,
            "mensaje": nueva_alerta.mensaje,
            "nivel_criticidad": nueva_alerta.nivel_criticidad,
            "push_enabled": push_enabled,
            "timestamp": nueva_alerta.timestamp_envio.isoformat(),
            "evidencia": {
                "deteccion_id": deteccion.id,
                "frame_url": f"/api/v1/detections/{deteccion.id}/frame",
                "latitud": float(deteccion.latitud),
                "longitud": float(deteccion.longitud),
                "altitud_metros": deteccion.altitud_metros,
                "checksum_sha256": deteccion.checksum_sha256,
            },
        }
        await notification_manager.broadcast_alert(payload_broadcast)

    return nuevo_evento
