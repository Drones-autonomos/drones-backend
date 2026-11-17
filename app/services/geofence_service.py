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