from datetime import datetime
from sqlalchemy.orm import Session
from app.models.flight_log import BitacoraVuelo

def log_flight_start(db: Session, vuelo_id: int, operador_id: int | None) -> BitacoraVuelo:
    entry = BitacoraVuelo(
        vuelo_id=vuelo_id,
        operador_id=operador_id,
        fecha_inicio=datetime.utcnow(),
        estado_final="EN_CURSO"
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
    resumen_telemetria: dict | None = None
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
        resumen_telemetria=resumen_telemetria
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry