from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, status
from sqlalchemy.orm import Session, joinedload

from app.api import deps
from app.models.alert import Alerta
from app.models.audit import Auditoria
from app.models.event import Evento
from app.models.user import Usuario
from app.schemas.alert import AlertaDetailResponse, AlertaResponse
from app.services.alert_service import (
    get_user_alert_states_map,
    serialize_alert_for_user,
    upsert_user_alert_state,
)
from app.services.notfication_service import notification_manager

router = APIRouter()


@router.get(
    "/",
    response_model=list[AlertaResponse],
    summary="Historial de alertas de seguridad enriquecido",
    description=(
        "Retorna el listado de alertas con evento y detecciones asociadas (sin N+1), "
        "incluyendo estado de lectura y descarte individual por usuario."
    ),
)
def list_alerts(
    leida: bool | None = Query(None, description="Filtrar por alertas leídas (true) o no leídas (false)"),
    nivel_criticidad: str | None = Query(None, description="Filtrar por criticidad (ej. ALTA, CRITICA)"),
    tipo: str | None = Query(
        None,
        description=(
            "Filtrar por tipo de evento "
            "(HUMO, INTRUSO, HUMO_DETECTADO, PERSONA_NOCTURNA, PERSONA_ZONA_RESTRINGIDA)"
        ),
    ),
    include_dismissed: bool = Query(False, description="Incluir alertas descartadas por el usuario actual"),
    skip: int = Query(0, ge=0, description="Número de registros a omitir para paginación"),
    limit: int = Query(50, ge=1, le=100, description="Cantidad máxima de alertas a retornar"),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    query = db.query(Alerta).options(joinedload(Alerta.evento).joinedload(Evento.detecciones))

    if nivel_criticidad:
        query = query.filter(Alerta.nivel_criticidad == nivel_criticidad.upper())

    if tipo:
        norm_tipo = tipo.strip().upper()
        query = query.join(Alerta.evento)
        if norm_tipo == "HUMO":
            query = query.filter(Evento.tipo == "HUMO_DETECTADO")
        elif norm_tipo == "INTRUSO":
            query = query.filter(Evento.tipo.in_(["PERSONA_NOCTURNA", "PERSONA_ZONA_RESTRINGIDA"]))
        else:
            query = query.filter(Evento.tipo == norm_tipo)

    if leida is not None:
        query = query.filter(Alerta.leida == leida)

    alertas = query.order_by(Alerta.timestamp_envio.desc()).offset(skip).limit(limit).all()
    states_map = get_user_alert_states_map(db, current_user.id, [a.id for a in alertas])

    result = []
    for alerta in alertas:
        state = states_map.get(alerta.id)
        if not include_dismissed and state and state.descartada_at is not None:
            continue
        result.append(serialize_alert_for_user(alerta, state))
    return result


@router.post(
    "/read-all",
    summary="Marcar todas las alertas pendientes como leídas para el usuario actual",
)
def mark_all_alerts_as_read(
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    alertas = db.query(Alerta).all()
    states_map = get_user_alert_states_map(db, current_user.id, [a.id for a in alertas])
    updated = 0
    for alerta in alertas:
        state = states_map.get(alerta.id)
        if state and state.descartada_at is not None:
            continue
        if not state or state.leida_at is None or not alerta.leida:
            alerta.leida = True
            upsert_user_alert_state(
                db,
                usuario_id=current_user.id,
                alerta_id=alerta.id,
                mark_read=True,
            )
            updated += 1
    db.commit()
    return {"updated": updated}


@router.get(
    "/{id}",
    response_model=AlertaDetailResponse,
    summary="Detalle completo de una alerta",
    description=(
        "Retorna la información de la alerta junto con el evento asociado, coordenadas y evidencias visuales."
    ),
)
def get_alert_detail(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    alerta = (
        db.query(Alerta)
        .options(joinedload(Alerta.evento).joinedload(Evento.detecciones))
        .filter(Alerta.id == id)
        .first()
    )
    if not alerta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alerta no encontrada",
        )
    states_map = get_user_alert_states_map(db, current_user.id, [alerta.id])
    return serialize_alert_for_user(alerta, states_map.get(alerta.id))


@router.patch(
    "/{id}/read",
    response_model=AlertaResponse,
    summary="Marcar alerta como leída por el usuario actual",
)
def mark_alert_as_read(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    alerta = (
        db.query(Alerta)
        .options(joinedload(Alerta.evento).joinedload(Evento.detecciones))
        .filter(Alerta.id == id)
        .first()
    )
    if not alerta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alerta no encontrada",
        )

    alerta.leida = True
    state = upsert_user_alert_state(
        db,
        usuario_id=current_user.id,
        alerta_id=alerta.id,
        mark_read=True,
    )
    db.commit()
    db.refresh(alerta)
    return serialize_alert_for_user(alerta, state)


@router.patch(
    "/{id}/dismiss",
    response_model=AlertaResponse,
    summary="Descartar alerta de la bandeja visible del usuario actual",
)
def dismiss_alert_for_user(
    id: int,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    alerta = (
        db.query(Alerta)
        .options(joinedload(Alerta.evento).joinedload(Evento.detecciones))
        .filter(Alerta.id == id)
        .first()
    )
    if not alerta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alerta no encontrada",
        )

    state = upsert_user_alert_state(
        db,
        usuario_id=current_user.id,
        alerta_id=alerta.id,
        mark_read=True,
        mark_dismissed=True,
    )
    db.add(
        Auditoria(
            usuario_id=current_user.id,
            accion="DESCARTAR_ALERTA",
            recurso=f"/api/v1/alerts/{alerta.id}/dismiss",
            detalle=f"Alerta #{alerta.id} descartada por {current_user.email}",
            ip_origen=request.client.host if request.client else "unknown",
        )
    )
    db.commit()
    db.refresh(alerta)
    return serialize_alert_for_user(alerta, state)


@router.websocket("/ws/notifications")
async def websocket_notifications(
    websocket: WebSocket,
    token: str | None = Query(None),
    db: Session = Depends(deps.get_db),
):
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        user = deps.get_current_user_ws_or_query(db, token)
        if not user.rol or user.rol.nombre not in ("GUARDIA", "ADMIN"):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await notification_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        notification_manager.disconnect(websocket)
