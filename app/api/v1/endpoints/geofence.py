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
    GeocercaUpdate,
    GeofenceCheckResponse,
    GeofencePointCheck,
    RouteValidateRequest,
    RouteValidateResponse,
    RouteViolation,
)
from app.services.geofence_service import (
    evaluate_route_against_zones,
    get_active_geofence_specs,
    validate_point_against_specs,
)

router = APIRouter()


@router.post(
    "/",
    response_model=GeocercaResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(deps.require_admin), Depends(deps.audit_action("CREAR_GEOCERCA"))],
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
        descripcion=geofence_in.descripcion,
        motivo=geofence_in.motivo,
        codigo_badge=geofence_in.codigo_badge,
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


@router.put(
    "/{id}",
    response_model=GeocercaResponse,
    dependencies=[Depends(deps.require_admin), Depends(deps.audit_action("EDITAR_GEOCERCA"))],
    summary="Editar geocerca operativa (Solo Admin)",
)
def update_geofence(
    id: int,
    geofence_in: GeocercaUpdate,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    row = db.query(Geocerca).filter(Geocerca.id == id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Geocerca no encontrada")

    update_data = geofence_in.model_dump(exclude_unset=True)
    if "poligono" in update_data:
        poligono = update_data.pop("poligono")
        row.poligono_json = json.dumps(poligono) if poligono else None
    for field, value in update_data.items():
        setattr(row, field, value)

    if row.altitud_min_m > row.altitud_max_m:
        raise HTTPException(
            status_code=422, detail="altitud_min_m no puede ser mayor a altitud_max_m"
        )

    db.commit()
    db.refresh(row)
    return GeocercaResponse.from_orm_model(row)


@router.patch(
    "/{id}/toggle",
    response_model=GeocercaResponse,
    dependencies=[Depends(deps.require_admin), Depends(deps.audit_action("TOGGLE_GEOCERCA"))],
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
    dependencies=[Depends(deps.require_admin), Depends(deps.audit_action("ELIMINAR_GEOCERCA"))],
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


@router.post(
    "/validate-route",
    response_model=RouteValidateResponse,
    summary="Validar una trayectoria completa contra geocercas y zonas de exclusión",
    description=(
        "Evalúa en una sola petición todos los waypoints de una ruta: cada punto "
        "debe caer dentro de alguna geocerca operativa activa y la trayectoria "
        "no debe cruzar zonas de exclusión `restringida` (respetando su tope "
        "`altitud_max_m`). Las zonas `advertencia` se reportan sin bloquear."
    ),
)
def validate_route(
    body: RouteValidateRequest,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    violations: list[RouteViolation] = []
    specs = get_active_geofence_specs(db)
    for idx, wp in enumerate(body.waypoints, 1):
        try:
            validate_point_against_specs(wp.latitud, wp.longitud, wp.altitud_metros, specs)
        except ValueError as exc:
            violations.append(
                RouteViolation(tipo="geocerca", motivo=str(exc), waypoint_index=idx)
            )
    error_zona, warnings = evaluate_route_against_zones(db, body.waypoints)
    if error_zona:
        violations.append(RouteViolation(tipo="exclusion", motivo=error_zona))
    violations.extend(RouteViolation(tipo="advertencia", motivo=w) for w in warnings)
    return RouteValidateResponse(
        valid=not any(v.tipo != "advertencia" for v in violations),
        violations=violations,
    )
