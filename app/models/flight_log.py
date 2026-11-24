import hashlib
import json
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, event, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.user import Usuario

GENESIS_HASH = "0" * 64


def compute_flight_log_hash(
    *,
    prev_hash: str,
    vuelo_id: int | None,
    operador_id: int | None,
    fecha_inicio: datetime,
    duracion_segundos: int,
    estado_final: str,
    incidentes: str | None,
    resumen_telemetria: dict | None = None,
) -> str:
    """Calcula de forma determinista el SHA-256 encadenado de un registro de bitácora."""
    ts_norm = fecha_inicio.replace(tzinfo=None).isoformat()
    resumen_norm = json.dumps(resumen_telemetria, sort_keys=True, ensure_ascii=False) if resumen_telemetria else ""
    canonical = "|".join(
        [
            prev_hash or GENESIS_HASH,
            "" if vuelo_id is None else str(vuelo_id),
            "" if operador_id is None else str(operador_id),
            ts_norm,
            str(duracion_segundos or 0),
            str(estado_final or ""),
            str(incidentes or ""),
            resumen_norm,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class BitacoraVuelo(Base):
    __tablename__ = "bitacora_vuelos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vuelo_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("misiones.id"), nullable=True)
    operador_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha_inicio: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    fecha_fin: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duracion_segundos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estado_final: Mapped[str] = mapped_column(String(30), default="EN_CURSO", nullable=False)
    incidentes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resumen_telemetria: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    operador: Mapped["Usuario | None"] = relationship("Usuario")


def _seal_flight_log_hash(mapper, connection, target: BitacoraVuelo):
    if target.fecha_inicio is None:
        target.fecha_inicio = datetime.utcnow()
    else:
        target.fecha_inicio = target.fecha_inicio.replace(tzinfo=None)

    if target.duracion_segundos is None:
        target.duracion_segundos = 0
    if not target.estado_final:
        target.estado_final = "EN_CURSO"

    if not target.prev_hash:
        last_row = connection.execute(
            text("SELECT hash_sha256 FROM bitacora_vuelos ORDER BY id DESC LIMIT 1")
        ).fetchone()
        target.prev_hash = (last_row[0] if last_row and last_row[0] else None) or GENESIS_HASH

    target.hash_sha256 = compute_flight_log_hash(
        prev_hash=target.prev_hash,
        vuelo_id=target.vuelo_id,
        operador_id=target.operador_id,
        fecha_inicio=target.fecha_inicio,
        duracion_segundos=target.duracion_segundos,
        estado_final=target.estado_final,
        incidentes=target.incidentes,
        resumen_telemetria=target.resumen_telemetria,
    )


def _block_flight_log_modification(mapper, connection, target):
    raise ValueError("Operación prohibida: registro inmutable (solo inserción).")


event.listen(BitacoraVuelo, "before_insert", _seal_flight_log_hash)
event.listen(BitacoraVuelo, "before_update", _block_flight_log_modification)
event.listen(BitacoraVuelo, "before_delete", _block_flight_log_modification)
