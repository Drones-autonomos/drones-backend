from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api import deps
from app.models.geofence import ZonaExclusion
from app.models.user import Usuario
from app.schemas.geofence import ZonaExclusionCreate, ZonaExclusionResponse

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
        query = query.filter(ZonaExclusion.activa == True)
    return query.order_by(ZonaExclusion.created_at.desc()).all()


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