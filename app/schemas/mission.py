from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.normative import (
    DEFAULT_ALTITUD_MAXIMA_M,
    validate_altitude,
    validate_operating_window,
    validate_weight,
)

ALTITUD_MAXIMA_NORMATIVA = DEFAULT_ALTITUD_MAXIMA_M


def utc_schedule(value):
    # La columna histórica usa timestamp sin zona; todos los valores se guardan en UTC.
    if value is not None and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


class WaypointBase(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    orden_waypoint: int = Field(..., ge=1, examples=[1])
    latitud: float = Field(..., ge=-90.0, le=90.0, examples=[20.5888])
    longitud: float = Field(..., ge=-180.0, le=180.0, examples=[-100.3899])
    altitud_metros: float = Field(default=15.0, ge=2.0, le=ALTITUD_MAXIMA_NORMATIVA, examples=[15.0])

    @field_validator("altitud_metros")
    @classmethod
    def validar_altitud(cls, v: float) -> float:
        return validate_altitude(v)


class WaypointResponse(WaypointBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class MisionBase(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=100)
    descripcion: str | None = None
    horario_inicio_programado: datetime | None = None
    normalize_schedule = field_validator("horario_inicio_programado")(utc_schedule)


class MisionCreate(MisionBase):
    peso_dron_kg: float = Field(default=2.5, gt=0.0, description="Peso total de la aeronave configurada")
    waypoints: list[WaypointBase] = Field(..., min_length=2)

    @field_validator("peso_dron_kg")
    @classmethod
    def validar_peso(cls, v: float) -> float:
        return validate_weight(v)

    @field_validator("horario_inicio_programado", mode="before")
    @classmethod
    def validar_horario_operativo(cls, value):
        if value is None:
            return None
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        validate_operating_window(parsed)
        return value

    @field_validator("waypoints")
    @classmethod
    def ordered_route(cls, value):
        if sorted(wp.orden_waypoint for wp in value) != list(range(1, len(value) + 1)):
            raise ValueError("Los waypoints deben tener órdenes únicos y consecutivos desde 1")
        return sorted(value, key=lambda wp: wp.orden_waypoint)


class MisionUpdate(BaseModel):
    nombre: str | None = None
    descripcion: str | None = None
    horario_inicio_programado: datetime | None = None
    normalize_schedule = field_validator("horario_inicio_programado")(utc_schedule)


class MisionResponse(MisionBase):
    id: int
    creado_por: int
    estado: str
    created_at: datetime
    iniciada_at: datetime | None = None
    finalizada_at: datetime | None = None
    waypoints_completados: int = 0
    error_ejecucion: str | None = None
    waypoints: list[WaypointResponse] = []

    model_config = ConfigDict(from_attributes=True)
