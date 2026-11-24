from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from app.api import deps
from app.models.audit import Auditoria
from app.models.event import Evento
from app.models.user import Usuario
from app.schemas.event import (
    EventoDetailResponse,
    EventoResponse,
    EventoStatusUpdate,
)
from app.services.notfication_service import notification_manager

router = APIRouter()


@router.get(
    "/",
    response_model=list[EventoResponse],
    summary="Listar eventos de seguridad",
    description=(
        "Retorna el listado de eventos con filtros opcionales de tipo, estado, "
        "rango de fechas y paginación. Accesible por Guardia y Admin."
    ),
)
def list_events(
    tipo: str | None = Query(
        None,
        description="Filtrar por tipo (ej. PERSONA_NOCTURNA, PERSONA_ZONA_RESTRINGIDA, HUMO_DETECTADO)",
    ),
    estado: str | None = Query(None, description="Filtrar por estado (ej. PENDIENTE, EN_REVISION, RESUELTO)"),
    fecha_inicio: datetime | None = Query(None, description="Fecha/hora inicial de búsqueda (ISO 8601)"),
    fecha_fin: datetime | None = Query(None, description="Fecha/hora final de búsqueda (ISO 8601)"),
    skip: int = Query(0, ge=0, description="Número de registros a omitir"),
    limit: int = Query(50, ge=1, le=100, description="Cantidad máxima de registros a retornar"),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    query = db.query(Evento)

    if tipo:
        query = query.filter(Evento.tipo == tipo.upper())
    if estado:
        query = query.filter(Evento.estado == estado.upper())
    if fecha_inicio:
        query = query.filter(Evento.created_at >= fecha_inicio)
    if fecha_fin:
        query = query.filter(Evento.created_at <= fecha_fin)

    eventos = query.order_by(Evento.created_at.desc()).offset(skip).limit(limit).all()
    return eventos


@router.get(
    "/{id}",
    response_model=EventoDetailResponse,
    summary="Obtener detalle de un evento",
    description=(
        "Retorna el detalle completo de un evento junto con sus detecciones y enlaces a evidencias."
    ),
)
def get_event(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    evento = db.query(Evento).options(joinedload(Evento.detecciones)).filter(Evento.id == id).first()
    if not evento:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento no encontrado",
        )
    return evento


@router.patch(
    "/{id}/status",
    response_model=EventoResponse,
    summary="Despachar guardia o resolver incidente de seguridad",
    description=(
        "Actualiza el estado del incidente a EN_REVISION (despacho de guardia) o RESUELTO (cierre), "
        "registrando responsable, marcas de tiempo, notas de resolución, auditoría y aviso WebSocket."
    ),
)
async def update_event_status(
    id: int,
    status_in: EventoStatusUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    evento = db.query(Evento).filter(Evento.id == id).first()
    if not evento:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento no encontrado",
        )

    ahora = datetime.utcnow()
    evento.estado = status_in.estado
    if status_in.notas_resolucion is not None:
        evento.notas_resolucion = status_in.notas_resolucion.strip() or None

    if status_in.estado == "EN_REVISION":
        if evento.atendido_por_id is None:
            evento.atendido_por_id = current_user.id
        if evento.despachado_at is None:
            evento.despachado_at = ahora
        accion_audit = "DESPACHAR_GUARDIA_EVENTO"
    else:
        if evento.atendido_por_id is None:
            evento.atendido_por_id = current_user.id
        if evento.despachado_at is None:
            evento.despachado_at = ahora
        evento.resuelto_por_id = current_user.id
        evento.resuelto_at = ahora
        accion_audit = "RESOLVER_EVENTO"

    db.add(
        Auditoria(
            usuario_id=current_user.id,
            accion=accion_audit,
            recurso=f"/api/v1/events/{evento.id}/status",
            detalle=(
                f"Estado={evento.estado} por {current_user.email}"
                + (f" · Nota: {evento.notas_resolucion}" if evento.notas_resolucion else "")
            ),
            ip_origen=request.client.host if request.client else "unknown",
        )
    )
    db.commit()
    db.refresh(evento)

    await notification_manager.broadcast_alert(
        {
            "type": "EVENT_UPDATED",
            "evento_id": evento.id,
            "estado": evento.estado,
            "atendido_por_id": evento.atendido_por_id,
            "resuelto_por_id": evento.resuelto_por_id,
            "notas_resolucion": evento.notas_resolucion,
            "updated_by": current_user.email,
            "timestamp": ahora.isoformat(),
        }
    )
    return evento
