from shapely.geometry import LineString, Point, box
from sqlalchemy.orm import Session
from app.models.geofence import ZonaExclusion

def validate_waypoints_against_geofences(db: Session, waypoints: list) -> str | None:
    zonas = db.query(ZonaExclusion).filter(ZonaExclusion.activa == True).all()
    if not zonas or not waypoints:
        return None

    coords = []
    for wp in waypoints:
        lat = wp.get("latitud") if isinstance(wp, dict) else getattr(wp, "latitud", getattr(wp, "latitude", None))
        lon = wp.get("longitud") if isinstance(wp, dict) else getattr(wp, "longitud", getattr(wp, "longitude", None))
        if lat is not None and lon is not None:
            coords.append((lon, lat))

    if not coords:
        return None

    ruta_geom = Point(coords[0]) if len(coords) == 1 else LineString(coords)

    for zona in zonas:
        poligono_exclusion = box(zona.lon_min, zona.lat_min, zona.lon_max, zona.lat_max)
        if ruta_geom.intersects(poligono_exclusion):
            return f"La trayectoria invade la zona de exclusión '{zona.nombre}'."
    return None
"""Validación geométrica de geocercas circulares y poligonales."""

import json
import math
from dataclasses import dataclass

from shapely.geometry import Point, Polygon
from sqlalchemy.orm import Session

from app.models.geofence import Geocerca


@dataclass(slots=True)
class GeofenceSpec:
    """Representación en memoria independiente de sesión ORM para validar puntos en vuelo."""

    nombre: str
    tipo: str
    centro_lat: float | None = None
    centro_lon: float | None = None
    radio_metros: float | None = None
    poligono: list[list[float]] | None = None
    altitud_min_m: float = 2.0
    altitud_max_m: float = 200.0


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_lat1, r_lat2 = math.radians(lat1), math.radians(lat2)
    dlat = r_lat2 - r_lat1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(r_lat1) * math.cos(r_lat2) * math.sin(dlon / 2) ** 2
    return 6371000.0 * 2.0 * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def to_spec(model: Geocerca) -> GeofenceSpec:
    return GeofenceSpec(
        nombre=model.nombre,
        tipo=model.tipo,
        centro_lat=model.centro_lat,
        centro_lon=model.centro_lon,
        radio_metros=model.radio_metros,
        poligono=json.loads(model.poligono_json) if model.poligono_json else None,
        altitud_min_m=model.altitud_min_m,
        altitud_max_m=model.altitud_max_m,
    )


def point_inside_geofence(lat: float, lon: float, alt_m: float, fence: GeofenceSpec) -> bool:
    if alt_m < fence.altitud_min_m or alt_m > fence.altitud_max_m:
        return False
    if fence.tipo == "CIRCULAR":
        if fence.centro_lat is None or fence.centro_lon is None or fence.radio_metros is None:
            return False
        return haversine_distance_m(lat, lon, fence.centro_lat, fence.centro_lon) <= fence.radio_metros
    if fence.tipo == "POLIGONO":
        if not fence.poligono or len(fence.poligono) < 3:
            return False
        polygon = Polygon([(float(p[1]), float(p[0])) for p in fence.poligono])
        return bool(polygon.covers(Point(float(lon), float(lat))))
    return False


def validate_point_against_specs(lat: float, lon: float, alt_m: float, specs: list[GeofenceSpec]) -> None:
    """Si existen geocercas activas, el punto debe ubicarse dentro de al menos una."""
    if not specs:
        return
    if any(point_inside_geofence(lat, lon, alt_m, fence) for fence in specs):
        return
    raise ValueError(f"Violación de geocerca: el punto ({lat}, {lon}, {alt_m}m) está fuera de las zonas autorizadas.")


def get_active_geofence_specs(db: Session) -> list[GeofenceSpec]:
    rows = db.query(Geocerca).filter(Geocerca.activa.is_(True)).all()
    return [to_spec(row) for row in rows]


def validate_waypoints_in_db(db: Session, waypoints) -> list[GeofenceSpec]:
    specs = get_active_geofence_specs(db)
    for wp in waypoints:
        validate_point_against_specs(float(wp.latitud), float(wp.longitud), float(wp.altitud_metros), specs)
    return specs
