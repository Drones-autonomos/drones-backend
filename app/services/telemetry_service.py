"""Servicio para registrar y consultar la bitácora de telemetría de vuelo."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.telemetry import TelemetriaVuelo
from app.schemas.telemetry import TelemetriaCreate


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
        return num if num == num else None  # filtra NaN
    except (TypeError, ValueError):
        return None


def capture_vehicle_snapshot(drone) -> dict:
    """Extrae telemetría enriquecida del vehículo conectado sin lanzar excepción si está desconectado."""
    now = datetime.now(UTC)
    vehicle = getattr(drone, "vehicle", None)
    if vehicle is None:
        return {
            "connected": False,
            "timestamp": now,
            "latitud": None,
            "longitud": None,
            "altitud_metros": None,
            "bateria_porcentaje": None,
            "voltaje_bateria": None,
            "velocidad_tierra_ms": None,
            "rumbo_grados": None,
            "modo_vuelo": None,
            "armado": False,
            "estado_enlace": "DESCONECTADO",
            "heartbeat_age_s": None,
        }

    heartbeat = _safe_float(getattr(vehicle, "last_heartbeat", None))
    link_state = "OK" if heartbeat is not None and heartbeat <= 5.0 else "PERDIDA_SENAL"

    location = getattr(vehicle, "location", None)
    rel = getattr(location, "global_relative_frame", None) if location else None
    battery = getattr(vehicle, "battery", None)
    mode = getattr(vehicle, "mode", None)

    return {
        "connected": True,
        "timestamp": now,
        "latitud": _safe_float(getattr(rel, "lat", None)),
        "longitud": _safe_float(getattr(rel, "lon", None)),
        "altitud_metros": _safe_float(getattr(rel, "alt", None)),
        "bateria_porcentaje": _safe_float(getattr(battery, "level", None)),
        "voltaje_bateria": _safe_float(getattr(battery, "voltage", None)),
        "velocidad_tierra_ms": _safe_float(getattr(vehicle, "groundspeed", None)),
        "rumbo_grados": _safe_float(getattr(vehicle, "heading", None)),
        "modo_vuelo": getattr(mode, "name", None),
        "armado": bool(getattr(vehicle, "armed", False)),
        "estado_enlace": link_state,
        "heartbeat_age_s": heartbeat,
    }


def save_telemetry_entry(db: Session, entry: TelemetriaCreate) -> TelemetriaVuelo:
    row = TelemetriaVuelo(
        mision_id=entry.mision_id,
        timestamp=entry.timestamp or datetime.now(UTC),
        latitud=entry.latitud,
        longitud=entry.longitud,
        altitud_metros=entry.altitud_metros,
        bateria_porcentaje=entry.bateria_porcentaje,
        voltaje_bateria=entry.voltaje_bateria,
        velocidad_tierra_ms=entry.velocidad_tierra_ms,
        rumbo_grados=entry.rumbo_grados,
        modo_vuelo=entry.modo_vuelo,
        armado=entry.armado,
        estado_enlace=entry.estado_enlace,
        heartbeat_age_s=entry.heartbeat_age_s,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def log_drone_snapshot(db: Session, drone, *, mision_id: int | None = None) -> TelemetriaVuelo:
    snap = capture_vehicle_snapshot(drone)
    entry = TelemetriaCreate(
        mision_id=mision_id,
        timestamp=snap["timestamp"],
        latitud=snap["latitud"],
        longitud=snap["longitud"],
        altitud_metros=snap["altitud_metros"],
        bateria_porcentaje=snap["bateria_porcentaje"],
        voltaje_bateria=snap["voltaje_bateria"],
        velocidad_tierra_ms=snap["velocidad_tierra_ms"],
        rumbo_grados=snap["rumbo_grados"],
        modo_vuelo=snap["modo_vuelo"],
        armado=snap["armado"],
        estado_enlace=snap["estado_enlace"],
        heartbeat_age_s=snap["heartbeat_age_s"],
    )
    return save_telemetry_entry(db, entry)
