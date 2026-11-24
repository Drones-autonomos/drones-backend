"""Servicio para registrar y consultar la bitácora de telemetría de vuelo."""

import math
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.patrol_routes import HOME_COORDS
from app.models.telemetry import TelemetriaVuelo
from app.schemas.telemetry import TelemetriaCreate

# Radio aproximado del campus/monitoreo alrededor de HOME para etiquetar la zona.
_CAMPUS_RADIUS_M = 600.0


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
        return num if num == num else None  # filtra NaN
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    num = _safe_float(value)
    return int(round(num)) if num is not None else None


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1.0, a)))


def _wind_snapshot(vehicle) -> tuple[float | None, float | None]:
    """Velocidad y dirección del viento desde DroneKit (no disponible en todo firmware)."""
    wind = getattr(vehicle, "wind", None)
    if callable(wind):
        try:
            wind = wind()
        except Exception:
            wind = None
    speed = _safe_float(getattr(wind, "speed", None) or getattr(vehicle, "wind_speed", None))
    direction = _safe_float(getattr(wind, "direction", None) or getattr(vehicle, "wind_direction", None))
    return (speed * 3.6 if speed is not None else None, direction)


def _signal_pct(heartbeat: float | None, enlace: str) -> int | None:
    if heartbeat is None:
        return None
    if enlace == "PERDIDA_SENAL":
        return 12
    return max(10, min(98, round(100 - heartbeat * 12)))


def _zone_snapshot(lat: float | None, lon: float | None, armado: bool) -> tuple[str | None, str | None]:
    if lat is None or lon is None:
        return None, None
    if _distance_m(lat, lon, HOME_COORDS[0], HOME_COORDS[1]) <= _CAMPUS_RADIUS_M:
        return "Campus FIF", "Monitoreo" if armado else "En base"
    return "Fuera de zona", "Fuera de cobertura"


def _disconnected_snapshot(now: datetime) -> dict:
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
        "viento_velocidad_kmh": None,
        "viento_direccion_deg": None,
        "satelites_gps": None,
        "gps_fix_type": None,
        "tilt_grados": None,
        "senal_rf_porcentaje": None,
        "latencia_ms": None,
        "zona_actual": None,
        "estado_zona": None,
        "failsafe_gcs_activo": None,
        "pausado": False,
    }


def capture_vehicle_snapshot(drone) -> dict:
    """Extrae telemetría enriquecida del vehículo conectado sin lanzar excepción si está desconectado."""
    now = datetime.now(UTC)
    vehicle = getattr(drone, "vehicle", None)
    if vehicle is None:
        return _disconnected_snapshot(now)

    heartbeat = _safe_float(getattr(vehicle, "last_heartbeat", None))
    link_state = "OK" if heartbeat is not None and heartbeat <= 5.0 else "PERDIDA_SENAL"

    location = getattr(vehicle, "location", None)
    rel = getattr(location, "global_relative_frame", None) if location else None
    battery = getattr(vehicle, "battery", None)
    mode = getattr(vehicle, "mode", None)
    armed = bool(getattr(vehicle, "armed", False))
    lat = _safe_float(getattr(rel, "lat", None))
    lon = _safe_float(getattr(rel, "lon", None))

    gps = getattr(vehicle, "gps_0", None)
    attitude = getattr(vehicle, "attitude", None)
    pitch = _safe_float(getattr(attitude, "pitch", None))
    wind_kmh, wind_deg = _wind_snapshot(vehicle)
    zona, estado_zona = _zone_snapshot(lat, lon, armed)

    params = getattr(vehicle, "parameters", None)
    failsafe = None
    if params is not None:
        try:
            failsafe = bool(int(float(params.get("FS_GCS_ENABLE", 0))))
        except (TypeError, ValueError):
            failsafe = None

    return {
        "connected": True,
        "timestamp": now,
        "latitud": lat,
        "longitud": lon,
        "altitud_metros": _safe_float(getattr(rel, "alt", None)),
        "bateria_porcentaje": _safe_float(getattr(battery, "level", None)),
        "voltaje_bateria": _safe_float(getattr(battery, "voltage", None)),
        "velocidad_tierra_ms": _safe_float(getattr(vehicle, "groundspeed", None)),
        "rumbo_grados": _safe_float(getattr(vehicle, "heading", None)),
        "modo_vuelo": getattr(mode, "name", None),
        "armado": armed,
        "estado_enlace": link_state,
        "heartbeat_age_s": heartbeat,
        "viento_velocidad_kmh": wind_kmh,
        "viento_direccion_deg": wind_deg,
        "satelites_gps": _safe_int(getattr(gps, "satellites_visible", None)),
        "gps_fix_type": _safe_int(getattr(gps, "fix_type", None)),
        "tilt_grados": math.degrees(pitch) if pitch is not None else None,
        "senal_rf_porcentaje": _signal_pct(heartbeat, link_state),
        "latencia_ms": heartbeat * 1000 if heartbeat is not None else None,
        "zona_actual": zona,
        "estado_zona": estado_zona,
        "failsafe_gcs_activo": failsafe,
        "pausado": bool(getattr(drone, "paused", False)),
    }


_TELEMETRY_EXTRA_FIELDS = (
    "viento_velocidad_kmh",
    "viento_direccion_deg",
    "satelites_gps",
    "gps_fix_type",
    "tilt_grados",
    "senal_rf_porcentaje",
    "latencia_ms",
    "zona_actual",
    "estado_zona",
    "failsafe_gcs_activo",
)


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
        **{field: getattr(entry, field) for field in _TELEMETRY_EXTRA_FIELDS},
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
        **{field: snap.get(field) for field in _TELEMETRY_EXTRA_FIELDS},
    )
    return save_telemetry_entry(db, entry)
