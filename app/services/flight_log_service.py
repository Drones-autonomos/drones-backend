from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.flight_log import GENESIS_HASH, BitacoraVuelo, compute_flight_log_hash


def log_flight_start(db: Session, vuelo_id: int, operador_id: int | None) -> BitacoraVuelo:
    entry = BitacoraVuelo(
        vuelo_id=vuelo_id,
        operador_id=operador_id,
        fecha_inicio=datetime.utcnow(),
        estado_final="EN_CURSO",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_flight_end(
    db: Session,
    vuelo_id: int,
    operador_id: int | None,
    fecha_inicio: datetime,
    estado_final: str,
    incidentes: str | None = None,
    resumen_telemetria: dict | None = None,
) -> BitacoraVuelo:
    ahora = datetime.utcnow()
    duracion = int((ahora - fecha_inicio).total_seconds())
    entry = BitacoraVuelo(
        vuelo_id=vuelo_id,
        operador_id=operador_id,
        fecha_inicio=fecha_inicio,
        fecha_fin=ahora,
        duracion_segundos=max(0, duracion),
        estado_final=estado_final,
        incidentes=incidentes,
        resumen_telemetria=resumen_telemetria,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def serialize_flight_log(entry: BitacoraVuelo) -> dict:
    operador = entry.operador
    rol_nombre = operador.rol.nombre if (operador and operador.rol) else None
    return {
        "id": entry.id,
        "vuelo_id": entry.vuelo_id,
        "operador_id": entry.operador_id,
        "operador_nombre": operador.nombre if operador else None,
        "operador_email": operador.email if operador else None,
        "operador_rol": rol_nombre,
        "fecha_inicio": entry.fecha_inicio.isoformat() if entry.fecha_inicio else None,
        "fecha_fin": entry.fecha_fin.isoformat() if entry.fecha_fin else None,
        "duracion_segundos": entry.duracion_segundos,
        "estado_final": entry.estado_final,
        "incidentes": entry.incidentes,
        "resumen_telemetria": entry.resumen_telemetria,
        "prev_hash": entry.prev_hash,
        "hash_sha256": entry.hash_sha256,
    }


def verify_flight_log_integrity(db: Session, log_id: int) -> dict | None:
    """Verifica el sello SHA-256 de un registro de bitácora y su enlace con el bloque previo."""
    entry = db.query(BitacoraVuelo).filter(BitacoraVuelo.id == log_id).first()
    if entry is None:
        return None

    previous = (
        db.query(BitacoraVuelo)
        .filter(BitacoraVuelo.id < entry.id)
        .order_by(BitacoraVuelo.id.desc())
        .first()
    )
    expected_prev_hash = (previous.hash_sha256 if previous and previous.hash_sha256 else GENESIS_HASH)
    actual_prev_hash = entry.prev_hash or GENESIS_HASH

    recomputed = compute_flight_log_hash(
        prev_hash=actual_prev_hash,
        vuelo_id=entry.vuelo_id,
        operador_id=entry.operador_id,
        fecha_inicio=entry.fecha_inicio,
        duracion_segundos=entry.duracion_segundos,
        estado_final=entry.estado_final,
        incidentes=entry.incidentes,
        resumen_telemetria=entry.resumen_telemetria,
    )
    hash_valid = bool(entry.hash_sha256 and recomputed == entry.hash_sha256)
    chain_valid = hash_valid and (actual_prev_hash == expected_prev_hash)

    return {
        "id": entry.id,
        "vuelo_id": entry.vuelo_id,
        "block_number": f"Bitácora #{entry.id}",
        "hash_sha256": entry.hash_sha256,
        "recomputed_hash": recomputed,
        "prev_hash": actual_prev_hash,
        "expected_prev_hash": expected_prev_hash,
        "hash_valid": hash_valid,
        "chain_valid": chain_valid,
        "is_immutable": True,
        "verified_at": datetime.now(UTC).isoformat(),
    }
