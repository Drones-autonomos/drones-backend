"""Schemas Pydantic para telemetría en vivo y bitácora de vuelo."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TelemetriaBase(BaseModel):
    mision_id: int | None = None
    latitud: float | None = Field(None, ge=-90.0, le=90.0)
    longitud: float | None = Field(None, ge=-180.0, le=180.0)
    altitud_metros: float | None = None
    bateria_porcentaje: float | None = Field(None, ge=0.0, le=100.0)
    voltaje_bateria: float | None = Field(None, ge=0.0)
    velocidad_tierra_ms: float | None = Field(None, ge=0.0)
    rumbo_grados: float | None = Field(None, ge=0.0, le=360.0)
    modo_vuelo: str | None = None
    armado: bool = False
    estado_enlace: str = "OK"
    heartbeat_age_s: float | None = None


class TelemetriaCreate(TelemetriaBase):
    timestamp: datetime | None = None


class TelemetriaResponse(TelemetriaBase):
    id: int
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class TelemetriaSnapshot(BaseModel):
    connected: bool
    timestamp: datetime
    latitud: float | None = None
    longitud: float | None = None
    altitud_metros: float | None = None
    bateria_porcentaje: float | None = None
    voltaje_bateria: float | None = None
    velocidad_tierra_ms: float | None = None
    rumbo_grados: float | None = None
    modo_vuelo: str | None = None
    armado: bool = False
    estado_enlace: str = "DESCONECTADO"
    heartbeat_age_s: float | None = None
