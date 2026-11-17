from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api import deps
from app.models.flight_log import BitacoraVuelo
from app.models.user import Usuario

router = APIRouter()

@router.get("/", summary="Consultar bitácora inmutable de vuelos")
def list_flight_logs(
    operador_id: int | None = Query(None),
    fecha_inicio: datetime | None = Query(None),
    fecha_fin: datetime | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    query = db.query(BitacoraVuelo)
    if operador_id:
        query = query.filter(BitacoraVuelo.operador_id == operador_id)
    if fecha_inicio:
        query = query.filter(BitacoraVuelo.fecha_inicio >= fecha_inicio)
    if fecha_fin:
        query = query.filter(BitacoraVuelo.fecha_inicio <= fecha_fin)

    return query.order_by(BitacoraVuelo.fecha_inicio.desc()).offset(skip).limit(limit).all()