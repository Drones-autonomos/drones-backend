from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.notfication_service import notification_manager

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api import deps
from app.models.alert import Alerta
from app.models.event import Evento
from app.models.user import Usuario
from app.schemas.alert import AlertaDetailResponse, AlertaResponse

router = APIRouter()


@router.get(
    "/",
    response_model=list[AlertaResponse],
    summary="Historial de alertas de seguridad",
    description="Retorna el listado de alertas generadas con filtros por estado de lectura y nivel de criticidad. Accesible por Guardia y Admin.",
)
def list_alerts(
    leida: bool | None = Query(None, description="Filtrar por alertas leídas (true) o no leídas (false)"),
    nivel_criticidad: str | None = Query(None, description="Filtrar por criticidad (ej. ALTA, CRITICA)"),
    skip: int = Query(0, ge=0, description="Número de registros a omitir para paginación"),
    limit: int = Query(50, ge=1, le=100, description="Cantidad máxima de alertas a retornar"),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    query = db.query(Alerta)

    if leida is not None:
        query = query.filter(Alerta.leida == leida)
    if nivel_criticidad:
        query = query.filter(Alerta.nivel_criticidad == nivel_criticidad.upper())

    alertas = query.order_by(Alerta.timestamp_envio.desc()).offset(skip).limit(limit).all()
    return alertas


@router.get(
    "/{id}",
    response_model=AlertaDetailResponse,
    summary="Detalle completo de una alerta",
    description="Retorna la información de la alerta junto con el evento asociado, coordenadas y evidencias visuales (frames).",
)
def get_alert_detail(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    alerta = (
        db.query(Alerta)
        .options(
            joinedload(Alerta.evento).joinedload(Evento.detecciones)
        )
        .filter(Alerta.id == id)
        .first()
    )
    if not alerta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alerta no encontrada",
        )
    return alerta


@router.patch(
    "/{id}/read",
    response_model=AlertaResponse,
    summary="Marcar alerta como leída",
    description="Actualiza el estado de lectura de la alerta a True.",
)
def mark_alert_as_read(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    alerta = db.query(Alerta).filter(Alerta.id == id).first()
    if not alerta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alerta no encontrada",
        )

    alerta.leida = True
    db.commit()
    db.refresh(alerta)
    return alerta

@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    await notification_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # Mantiene vivo el canal
    except WebSocketDisconnect:
        notification_manager.disconnect(websocket)