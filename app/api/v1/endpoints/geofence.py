"""Endpoints REST para administrar geocercas y validar coordenadas."""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api import deps
from app.models.geofence import Geocerca
from app.models.user import Usuario
from app.schemas.geofence import (
    GeocercaCreate,
    GeocercaResponse,
    GeofenceCheckResponse,
    GeofencePointCheck,
)
from app.services.geofence_service import get_active_geofence_specs, validate_point_against_specs

router = APIRouter()


@router.post(
    "/",
    response_model=GeocercaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear geocerca operativa (Solo Admin)",
)
def create_geofence(
    geofence_in: GeocercaCreate,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    row = Geocerca(
        nombre=geofence_in.nombre,
        tipo=geofence_in.tipo,
        activa=geofence_in.activa,
        centro_lat=geofence_in.centro_lat,
        centro_lon=geofence_in.centro_lon,
        radio_metros=geofence_in.radio_metros,
        poligono_json=json.dumps(geofence_in.poligono) if geofence_in.poligono else None,
        altitud_min_m=geofence_in.altitud_min_m,
        altitud_max_m=geofence_in.altitud_max_m,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return GeocercaResponse.from_orm_model(row)


@router.get(
    "/",
    response_model=list[GeocercaResponse],
    summary="Listar geocercas configuradas",
)
def list_geofences(
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    rows = db.query(Geocerca).order_by(Geocerca.id.asc()).all()
    return [GeocercaResponse.from_orm_model(r) for r in rows]


@router.patch(
    "/{id}/toggle",
    response_model=GeocercaResponse,
    summary="Activar o desactivar una geocerca",
)
def toggle_geofence(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    row = db.query(Geocerca).filter(Geocerca.id == id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Geocerca no encontrada")
    row.activa = not row.activa
    db.commit()
    db.refresh(row)
    return GeocercaResponse.from_orm_model(row)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar geocerca",
)
def delete_geofence(
    id: int,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    row = db.query(Geocerca).filter(Geocerca.id == id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Geocerca no encontrada")
    db.delete(row)
    db.commit()


@router.post(
    "/validate-point",
    response_model=GeofenceCheckResponse,
    summary="Validar si una coordenada cumple las geocercas activas",
)
def validate_point(
    point: GeofencePointCheck,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    specs = get_active_geofence_specs(db)
    try:
        validate_point_against_specs(point.latitud, point.longitud, point.altitud_metros, specs)
    except ValueError as exc:
        return GeofenceCheckResponse(permitido=False, motivo=str(exc))
    return GeofenceCheckResponse(permitido=True, motivo="Coordenada dentro de geocerca autorizada")
