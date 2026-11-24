from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api import deps
from app.models.geofence import ZonaExclusion
from app.models.user import Usuario
from app.schemas.geofence import ZonaExclusionCreate, ZonaExclusionResponse, ZonaExclusionUpdate

router = APIRouter()


@router.post(
    "/",
    response_model=ZonaExclusionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(deps.audit_action("CREAR_ZONA_EXCLUSION"))],
    summary="Registrar zona de exclusión rectangular",
    description="Crea un polígono rectangular restringido para validación de rutas y visualización en Leaflet.",
)
def create_exclusion_zone(
    zona_in: ZonaExclusionCreate,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    nueva_zona = ZonaExclusion(
        nombre=zona_in.nombre,
        lat_min=zona_in.lat_min,
        lat_max=zona_in.lat_max,
        lon_min=zona_in.lon_min,
        lon_max=zona_in.lon_max,
        activa=zona_in.activa,
        clasificacion=zona_in.clasificacion,
        motivo=zona_in.motivo,
        descripcion=zona_in.descripcion,
        codigo_badge=zona_in.codigo_badge,
        altitud_max_m=zona_in.altitud_max_m,
    )
    db.add(nueva_zona)
    db.commit()
    db.refresh(nueva_zona)
    return nueva_zona


@router.get(
    "/",
    response_model=list[ZonaExclusionResponse],
    summary="Listar zonas de exclusión",
    description="Retorna las zonas rectangulares registradas para dibujarlas en el mapa Leaflet.",
)
def list_exclusion_zones(
    solo_activas: bool = Query(True, description="Filtrar únicamente zonas activas"),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    query = db.query(ZonaExclusion)
    if solo_activas:
        query = query.filter(ZonaExclusion.activa.is_(True))
    return query.order_by(ZonaExclusion.created_at.desc()).all()


@router.put(
    "/{geofence_id}",
    response_model=ZonaExclusionResponse,
    dependencies=[Depends(deps.audit_action("EDITAR_ZONA_EXCLUSION"))],
    summary="Editar zona de exclusión (Solo Admin)",
)
def update_exclusion_zone(
    geofence_id: int,
    zona_in: ZonaExclusionUpdate,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    zona = db.query(ZonaExclusion).filter(ZonaExclusion.id == geofence_id).first()
    if not zona:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Zona de exclusión no encontrada.",
        )
    for field, value in zona_in.model_dump(exclude_unset=True).items():
        setattr(zona, field, value)
    if zona.lat_min >= zona.lat_max or zona.lon_min >= zona.lon_max:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Los límites de la zona deben respetar min < max.",
        )
    db.commit()
    db.refresh(zona)
    return zona


@router.patch(
    "/{geofence_id}/toggle",
    response_model=ZonaExclusionResponse,
    dependencies=[Depends(deps.audit_action("TOGGLE_ZONA_EXCLUSION"))],
    summary="Activar o pausar zona de exclusión (Solo Admin)",
)
def toggle_exclusion_zone(
    geofence_id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    zona = db.query(ZonaExclusion).filter(ZonaExclusion.id == geofence_id).first()
    if not zona:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Zona de exclusión no encontrada.",
        )
    zona.activa = not zona.activa
    db.commit()
    db.refresh(zona)
    return zona


@router.delete(
    "/{geofence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(deps.audit_action("ELIMINAR_ZONA_EXCLUSION"))],
    summary="Desactivar o eliminar zona de exclusión (Solo Admin)",
)
def delete_exclusion_zone(
    geofence_id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    zona = db.query(ZonaExclusion).filter(ZonaExclusion.id == geofence_id).first()
    if not zona:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Zona de exclusión no encontrada.",
        )
    db.delete(zona)
    db.commit()
    return None
