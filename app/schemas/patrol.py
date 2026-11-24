"""Schemas de las rutas de patrullaje preprogramadas (GET /missions/presets)."""

from pydantic import BaseModel, Field


class PatrolWaypoint(BaseModel):
    """Waypoint de una ruta preprogramada; ``hover_s`` indica segundos de
    inspección sobre el punto (solo barrido, opcional)."""

    latitud: float = Field(..., ge=-90.0, le=90.0, examples=[20.704086])
    longitud: float = Field(..., ge=-180.0, le=180.0, examples=[-100.443178])
    hover_s: float | None = Field(default=None, ge=0.0, examples=[2])


class PatrolBase(BaseModel):
    """Base fija del circuito de patrullaje (HOME, Base 1, Base 2)."""

    id: str = Field(..., examples=["base1"])
    label: str = Field(..., examples=["B1"])
    tooltip: str = Field(..., examples=["Base 1 · acceso sureste del campus"])
    coords: list[float] = Field(..., min_length=2, max_length=2, examples=[[20.701383, -100.441494]])


class PatrolPreset(BaseModel):
    """Ruta de patrullaje preprogramada lista para cargar en el mapa.

    ``waypoints`` es el trayecto completo ordenado:
    HOME → traslado → Base 1 → barrido → Base 2 → regreso → Base 1.
    """

    id: str = Field(..., examples=["clasica"])
    name: str = Field(..., examples=["Patrullaje Clásica"])
    description: str
    altitude_m: float = Field(..., description="Altitud relativa sugerida (AGL) en metros", examples=[30.0])
    waypoints: list[PatrolWaypoint]
    route_length_m: float = Field(..., description="Longitud total del trayecto en metros")
    clearance_m: float = Field(..., description="Clareo mínimo a zonas de interferencia en metros")
    bases: list[PatrolBase]
    home: list[float] = Field(..., min_length=2, max_length=2, examples=[[20.70428, -100.44358]])
