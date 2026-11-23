from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ZonaExclusionCreate(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=100, description="Nombre identificador de la zona")
    lat_min: float = Field(..., ge=-90.0, le=90.0)
    lat_max: float = Field(..., ge=-90.0, le=90.0)
    lon_min: float = Field(..., ge=-180.0, le=180.0)
    lon_max: float = Field(..., ge=-180.0, le=180.0)
    activa: bool = True

    @model_validator(mode="after")
    def validar_limites_rectangulo(self):
        if self.lat_min >= self.lat_max:
            raise ValueError("lat_min debe ser estrictamente menor que lat_max.")
        if self.lon_min >= self.lon_max:
            raise ValueError("lon_min debe ser estrictamente menor que lon_max.")
        return self


class ZonaExclusionResponse(ZonaExclusionCreate):
    id: int
"""Schemas Pydantic para geocercas operativas y validación de puntos."""

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GeocercaCreate(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=100)
    tipo: str = Field(..., pattern="^(CIRCULAR|POLIGONO)$")
    activa: bool = True
    centro_lat: float | None = Field(None, ge=-90.0, le=90.0)
    centro_lon: float | None = Field(None, ge=-180.0, le=180.0)
    radio_metros: float | None = Field(None, gt=0.0, le=50000.0)
    poligono: list[tuple[float, float]] | None = None
    altitud_min_m: float = Field(default=2.0, ge=0.0, le=200.0)
    altitud_max_m: float = Field(default=200.0, ge=2.0, le=200.0)

    @model_validator(mode="after")
    def validate_geometry(self):
        if self.altitud_min_m > self.altitud_max_m:
            raise ValueError("altitud_min_m no puede ser mayor a altitud_max_m")
        if self.tipo == "CIRCULAR":
            if self.centro_lat is None or self.centro_lon is None or self.radio_metros is None:
                raise ValueError("Geocerca CIRCULAR requiere centro_lat, centro_lon y radio_metros")
        elif self.tipo == "POLIGONO":
            if not self.poligono or len(self.poligono) < 3:
                raise ValueError("Geocerca POLIGONO requiere al menos 3 vértices [lat, lon]")
        return self


class GeocercaResponse(BaseModel):
    id: int
    nombre: str
    tipo: str
    activa: bool
    centro_lat: float | None = None
    centro_lon: float | None = None
    radio_metros: float | None = None
    poligono: list[list[float]] | None = None
    altitud_min_m: float
    altitud_max_m: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DroneConnectionEventCreate(BaseModel):
    vuelo_id: int | None = Field(None, description="ID de la misión o vuelo activo")
    estado_enlace: Literal["ONLINE", "WEAK_SIGNAL", "DISCONNECTED_RTL"] = Field(
        ..., description="Estado de conectividad reportado por SITL/MAVProxy"
    )
    detalle: str | None = Field(None, description="Información adicional o coordenadas del evento")
    bateria_porcentaje: float | None = Field(None, ge=0.0, le=100.0)
    @classmethod
    def from_orm_model(cls, obj) -> "GeocercaResponse":
        poly = json.loads(obj.poligono_json) if obj.poligono_json else None
        return cls(
            id=obj.id,
            nombre=obj.nombre,
            tipo=obj.tipo,
            activa=obj.activa,
            centro_lat=obj.centro_lat,
            centro_lon=obj.centro_lon,
            radio_metros=obj.radio_metros,
            poligono=poly,
            altitud_min_m=obj.altitud_min_m,
            altitud_max_m=obj.altitud_max_m,
            created_at=obj.created_at,
        )


class GeofencePointCheck(BaseModel):
    latitud: float = Field(..., ge=-90.0, le=90.0)
    longitud: float = Field(..., ge=-180.0, le=180.0)
    altitud_metros: float = Field(default=15.0, ge=0.0, le=200.0)


class GeofenceCheckResponse(BaseModel):
    permitido: bool
    motivo: str
