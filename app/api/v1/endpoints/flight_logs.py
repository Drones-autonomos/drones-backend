from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api import deps
from app.models.flight_log import BitacoraVuelo
from app.models.user import Usuario
from app.services.flight_log_service import serialize_flight_log, verify_flight_log_integrity

router = APIRouter()


@router.get("/", summary="Consultar bitácora inmutable de vuelos con sello SHA-256")
def list_flight_logs(
    vuelo_id: int | None = Query(None),
    operador_id: int | None = Query(None),
    fecha_inicio: datetime | None = Query(None),
    fecha_fin: datetime | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    query = db.query(BitacoraVuelo).options(joinedload(BitacoraVuelo.operador).joinedload(Usuario.rol))
    if vuelo_id is not None:
        query = query.filter(BitacoraVuelo.vuelo_id == vuelo_id)
    if operador_id is not None:
        query = query.filter(BitacoraVuelo.operador_id == operador_id)
    if fecha_inicio:
        query = query.filter(BitacoraVuelo.fecha_inicio >= fecha_inicio)
    if fecha_fin:
        query = query.filter(BitacoraVuelo.fecha_inicio <= fecha_fin)

    rows = query.order_by(BitacoraVuelo.fecha_inicio.desc(), BitacoraVuelo.id.desc()).offset(skip).limit(limit).all()
    return [serialize_flight_log(row) for row in rows]


@router.get("/{id}/verify", summary="Verificar integridad criptográfica SHA-256 de un registro de bitácora")
def verify_flight_log(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    result = verify_flight_log_integrity(db, id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registro de bitácora no encontrado",
        )
    return result
