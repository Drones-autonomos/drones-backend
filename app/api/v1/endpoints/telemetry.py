"""Endpoints REST para telemetría en vivo y bitácora persistente de vuelos."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api import deps
from app.models.telemetry import TelemetriaVuelo
from app.models.user import Usuario
from app.schemas.telemetry import TelemetriaCreate, TelemetriaResponse, TelemetriaSnapshot
from app.services.drone_service import drone_service
from app.services.telemetry_service import capture_vehicle_snapshot, save_telemetry_entry

router = APIRouter()


@router.get(
    "/current",
    response_model=TelemetriaSnapshot,
    summary="Telemetría actual del dron",
)
def get_current_telemetry(current_user: Usuario = Depends(deps.require_guard_or_admin)):
    return TelemetriaSnapshot(**capture_vehicle_snapshot(drone_service))


@router.get(
    "/log",
    response_model=list[TelemetriaResponse],
    summary="Bitácora histórica de telemetría",
)
def list_telemetry_log(
    mision_id: int | None = Query(None, description="Filtrar muestras por ID de misión"),
    estado_enlace: str | None = Query(None, description="Filtrar por estado de enlace (OK, PERDIDA_SENAL)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    query = db.query(TelemetriaVuelo)
    if mision_id is not None:
        query = query.filter(TelemetriaVuelo.mision_id == mision_id)
    if estado_enlace:
        query = query.filter(TelemetriaVuelo.estado_enlace == estado_enlace.upper())
    return query.order_by(TelemetriaVuelo.timestamp.desc()).offset(skip).limit(limit).all()


@router.post(
    "/log",
    response_model=TelemetriaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar entrada de telemetría en bitácora",
)
def create_telemetry_entry(
    entry: TelemetriaCreate,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    return save_telemetry_entry(db, entry)
