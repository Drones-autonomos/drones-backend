from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api import deps
from app.models.mission import Mision, Ruta
from app.models.user import Usuario
from app.schemas.mission import (
    MisionCreate,
    MisionResponse,
    MisionUpdate,
)

router = APIRouter()


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
    # 1. Crear la cabecera de la misión asociada al usuario actual
    nueva_mision = Mision(
        creado_por=current_user.id,
        nombre=mission_in.nombre,
        descripcion=mission_in.descripcion,
        horario_inicio_programado=mission_in.horario_inicio_programado,
        estado="PROGRAMADA",
    )
    db.add(nueva_mision)
    db.flush()  # Genera el ID de la misión sin hacer commit aún

    # 2. Crear los waypoints vinculados
    for wp in mission_in.waypoints:
        nuevo_wp = Ruta(
            mision_id=nueva_mision.id,
            orden_waypoint=wp.orden_waypoint,
            latitud=wp.latitud,
            longitud=wp.longitud,
            altitud_metros=wp.altitud_metros,
        )
        db.add(nuevo_wp)

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
        description="Filtrar por estado: PROGRAMADA, EN_CURSO, FINALIZADA, CANCELADA",
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
    for field, value in update_data.items():
        setattr(mision, field, value)

    db.commit()
    db.refresh(mision)
    return mision


@router.post(
    "/{id}/cancel",
    response_model=MisionResponse,
    dependencies=[Depends(deps.require_guard_or_admin)],
    summary="Cancelar misión",
    description=("Cambia el estado de la misión a CANCELADA. Accesible tanto por guardia como por admin."),
)
def cancel_mission(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    mision = db.query(Mision).filter(Mision.id == id).first()
    if not mision:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Misión no encontrada")

    if mision.estado in ["FINALIZADA", "CANCELADA"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La misión ya no puede ser cancelada (estado actual: {mision.estado})",
        )

    mision.estado = "CANCELADA"
    db.commit()
    db.refresh(mision)
    return mision
