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
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DroneConnectionEventCreate(BaseModel):
    vuelo_id: int | None = Field(None, description="ID de la misión o vuelo activo")
    estado_enlace: Literal["ONLINE", "WEAK_SIGNAL", "DISCONNECTED_RTL"] = Field(
        ..., description="Estado de conectividad reportado por SITL/MAVProxy"
    )
    detalle: str | None = Field(None, description="Información adicional o coordenadas del evento")
    bateria_porcentaje: float | None = Field(None, ge=0.0, le=100.0)