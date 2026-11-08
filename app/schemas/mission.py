from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    altitud_metros: float = Field(default=15.0, ge=2.0, le=200.0, examples=[15.0])


class WaypointResponse(WaypointBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class MisionBase(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=100)
    descripcion: str | None = None
    horario_inicio_programado: datetime | None = None
    normalize_schedule = field_validator("horario_inicio_programado")(utc_schedule)


class MisionCreate(MisionBase):
    waypoints: list[WaypointBase] = Field(..., min_length=2)

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
