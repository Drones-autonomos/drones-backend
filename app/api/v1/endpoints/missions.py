import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.core.patrol_routes import get_patrol_presets
from app.models.mission import Mision, Ruta
from app.models.user import Usuario
from app.schemas.mission import (
    MisionCreate,
    MisionResponse,
    MisionUpdate,
)
from app.schemas.patrol import PatrolPreset
from app.services.geofence_service import validate_waypoints_against_geofences, validate_waypoints_in_db
from app.services.mission_service import MissionService, get_mission_service

router = APIRouter()


def _persist_ruta(mision_id: int, wp, db: Session) -> Ruta:
    row = Ruta(
        mision_id=mision_id,
        orden_waypoint=wp.orden_waypoint,
        latitud=wp.latitud,
        longitud=wp.longitud,
        altitud_metros=wp.altitud_metros,
        hover_segundos=wp.hover_segundos,
    )
    db.add(row)
    return row


@router.post(
    "/",
    response_model=MisionResponse,
    dependencies=[Depends(deps.require_admin)],
    status_code=status.HTTP_201_CREATED,
    summary="Crear misión con waypoints",
    description="Crea una misión y registra sus waypoints de ruta en una sola transacción. Requiere rol ADMIN.",
)
def create_mission(
    mission_in: MisionCreate,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    try:
        validate_waypoints_in_db(db, mission_in.waypoints)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    # 1. Crear la cabecera de la misión asociada al usuario actual
    nueva_mision = Mision(
        creado_por=current_user.id,
        nombre=mission_in.nombre,
        descripcion=mission_in.descripcion,
        horario_inicio_programado=mission_in.horario_inicio_programado,
        horario_fin_programado=mission_in.horario_fin_programado,
        duracion_estimada_min=mission_in.duracion_estimada_min,
        helipuerto_salida=mission_in.helipuerto_salida,
        helipuerto_llegada=mission_in.helipuerto_llegada,
        es_recurrente=mission_in.es_recurrente,
        dias_semana_json=json.dumps(mission_in.dias_semana) if mission_in.dias_semana else None,
        evitacion_exclusion=mission_in.evitacion_exclusion,
        bateria_minima_pct=mission_in.bateria_minima_pct,
        sensor_optico=mission_in.sensor_optico,
        estado="PROGRAMADA",
    )
    # 1. Validar que los waypoints no crucen ninguna zona de exclusión activa (Geofencing)
    if mission_in.evitacion_exclusion:
        error_geofence = validate_waypoints_against_geofences(db, mission_in.waypoints)
        if error_geofence:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_geofence,
            )


    db.add(nueva_mision)
    db.flush()  # Genera el ID de la misión sin hacer commit aún

    # 2. Crear los waypoints vinculados
    for wp in mission_in.waypoints:
        _persist_ruta(nueva_mision.id, wp, db)

    db.commit()
    db.refresh(nueva_mision)
    return nueva_mision


@router.get(
    "/",
    response_model=list[MisionResponse],
    dependencies=[Depends(deps.require_guard_or_admin)],
    summary="Listar misiones",
    description="Retorna el listado de misiones con filtros de paginación y estado[cite: 2].",
)
def list_missions(
    estado: str | None = Query(
        None,
        description="Estado: PROGRAMADA, EN_CURSO, CANCELANDO, FINALIZADA, CANCELADA, FALLIDA o RECUPERACION",
    ),
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(50, ge=1, le=100, description="Límite por página"),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    query = db.query(Mision)
    if estado:
        query = query.filter(Mision.estado == estado.upper())
    misiones = query.order_by(Mision.created_at.desc()).offset(skip).limit(limit).all()
    return misiones


# NOTA: "/presets" debe declararse ANTES que "/{id}" — de lo contrario el
# path param capturaría el literal "presets" y fallaría la conversión a int.
@router.get(
    "/presets",
    response_model=list[PatrolPreset],
    dependencies=[Depends(deps.require_guard_or_admin)],
    summary="Rutas de patrullaje preprogramadas",
    description=(
        "Devuelve las variantes de patrullaje del campus validadas contra las "
        "zonas de interferencia (traslado + barrido + regreso a Base 1), con "
        "las bases fijas y HOME. Requiere rol ADMIN o GUARDIA."
    ),
)
def list_patrol_presets(
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    return get_patrol_presets()


class SchedulerToggleRequest(BaseModel):
    enabled: bool


# NOTA: "/scheduler" también debe declararse ANTES que "/{id}".
@router.get(
    "/scheduler",
    dependencies=[Depends(deps.require_guard_or_admin)],
    summary="Estado del scheduler de vuelo autónomo",
)
def get_scheduler(
    service: MissionService = Depends(get_mission_service),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    return service.scheduler_status()


@router.put(
    "/scheduler",
    dependencies=[Depends(deps.require_admin)],
    summary="Activar o pausar el scheduler de vuelo autónomo",
)
def set_scheduler(
    body: SchedulerToggleRequest,
    service: MissionService = Depends(get_mission_service),
    current_user: Usuario = Depends(deps.require_admin),
):
    return service.set_scheduler_enabled(body.enabled)


@router.get(
    "/{id}",
    response_model=MisionResponse,
    summary="Obtener misión por ID",
    description="Retorna el detalle completo y sus waypoints en orden[cite: 2].",
)
def get_mission(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    mision = db.query(Mision).filter(Mision.id == id).first()
    if not mision:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Misión no encontrada")
    return mision


@router.put(
    "/{id}",
    response_model=MisionResponse,
    summary="Editar misión",
    description="Edita datos informativos mientras la misión se encuentre en estado PROGRAMADA[cite: 2].",
)
def update_mission(
    id: int,
    mission_in: MisionUpdate,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    mision = db.query(Mision).filter(Mision.id == id).first()
    if not mision:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Misión no encontrada")

    if mision.estado != "PROGRAMADA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("No se puede modificar una misión que ya no está en estado PROGRAMADA"),
        )

    update_data = mission_in.model_dump(exclude_unset=True)

    if "waypoints" in update_data and update_data["waypoints"] is not None:
        waypoints = mission_in.waypoints
        try:
            validate_waypoints_in_db(db, waypoints)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        error_geofence = validate_waypoints_against_geofences(db, waypoints)
        if error_geofence:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=error_geofence
            )
        for row in list(mision.waypoints):
            db.delete(row)
        db.flush()
        for wp in waypoints:
            _persist_ruta(mision.id, wp, db)
    update_data.pop("waypoints", None)

    if "dias_semana" in update_data:
        dias = update_data.pop("dias_semana")
        mision.dias_semana_json = json.dumps(dias) if dias else None

    for field, value in update_data.items():
        setattr(mision, field, value)

    db.commit()
    db.refresh(mision)
    return mision


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(deps.require_admin)],
    summary="Eliminar misión",
    description=(
        "Elimina una misión en estado PROGRAMADA, CANCELADA, FINALIZADA o FALLIDA. "
        "Rechaza misiones en curso o con reserva del vehículo."
    ),
)
def delete_mission(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    mision = db.query(Mision).filter(Mision.id == id).first()
    if not mision:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Misión no encontrada")
    if mision.vehiculo_activo == 1 or mision.estado not in ("PROGRAMADA", "CANCELADA", "FALLIDA"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se pueden eliminar misiones PROGRAMADA, CANCELADA o FALLIDA",
        )
    db.delete(mision)
    db.commit()


@router.post(
    "/{id}/cancel",
    response_model=MisionResponse,
    dependencies=[Depends(deps.require_guard_or_admin)],
    summary="Cancelar misión",
    description=("Cancela misiones programadas o solicita interrupción con RTL. Requiere ADMIN o GUARDIA."),
)
def cancel_mission(
    id: int,
    service: MissionService = Depends(get_mission_service),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    service.cancel(id)
    db.expire_all()
    return db.get(Mision, id)


@router.post("/{id}/start", response_model=MisionResponse, status_code=202, summary="Iniciar ejecución de la ruta")
def start_mission(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
    service: MissionService = Depends(get_mission_service),
):
    service.start(id, ejecutado_por=current_user.id)
    db.expire_all()
    return db.get(Mision, id)


@router.post("/{id}/confirm-landed", response_model=MisionResponse, summary="Recuperar reserva tras interrupción")
def confirm_landed(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
    service: MissionService = Depends(get_mission_service),
):
    service.confirm_landed(id)
    db.expire_all()
    return db.get(Mision, id)
