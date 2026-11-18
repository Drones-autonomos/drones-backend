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
