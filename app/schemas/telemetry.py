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
    viento_velocidad_kmh: float | None = Field(None, ge=0.0)
    viento_direccion_deg: float | None = Field(None, ge=0.0, le=360.0)
    satelites_gps: int | None = Field(None, ge=0)
    gps_fix_type: int | None = Field(None, ge=0)
    tilt_grados: float | None = None
    senal_rf_porcentaje: int | None = Field(None, ge=0, le=100)
    latencia_ms: float | None = Field(None, ge=0.0)
    zona_actual: str | None = None
    estado_zona: str | None = None
    failsafe_gcs_activo: bool | None = None


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
    viento_velocidad_kmh: float | None = None
    viento_direccion_deg: float | None = None
    satelites_gps: int | None = None
    gps_fix_type: int | None = None
    tilt_grados: float | None = None
    senal_rf_porcentaje: int | None = None
    latencia_ms: float | None = None
    zona_actual: str | None = None
    estado_zona: str | None = None
    failsafe_gcs_activo: bool | None = None
    pausado: bool = False
