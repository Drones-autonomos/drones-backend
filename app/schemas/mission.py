from datetime import UTC, datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALTITUD_MAXIMA_NORMATIVA = 200.0 #metros
PESO_MAXIMO_NORMATIVO = 5.0 #kg

def utc_schedule(value):
    # La columna histórica usa timestamp sin zona; todos los valores se guardan en UTC.
    if value is not None and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value

class WaypointCreate(BaseModel):
    orden_waypoint: int
    latitud: float
    longitud: float
    altitud_metros: float = Field(..., description="Altitud en metros sobre el suelo")

    @field_validator("altitud_metros")
    @classmethod
    def validar_altitud(cls, v: float) -> float:
        if v > ALTITUD_MAXIMA_NORMATIVA:
            raise ValueError(f"Violación normativa (RNF-07): La altitud máxima permitida es de {ALTITUD_MAXIMA_NORMATIVA} m. Recibido: {v} m.")
        if v <= 0:
            raise ValueError("La altitud debe ser mayor a 0 metros.")
        return v

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

class MisionCreate(BaseModel):
    nombre: str
    descripcion: str | None = None
    horario_inicio_programado: datetime
    peso_dron_kg: float = Field(default=2.5, description="Peso total de la aeronave configurada")
    waypoints: list[WaypointCreate]

    @field_validator("peso_dron_kg")
    @classmethod
    def validar_peso(cls, v: float) -> float:
        if v > PESO_MAXIMO_NORMATIVO:
            raise ValueError(f"Violación normativa: El peso excede el límite permitido de {PESO_MAXIMO_NORMATIVO} kg.")
        return v

    @field_validator("horario_inicio_programado")
    @classmethod
    def validar_horario_operativo(cls, v: datetime) -> datetime:
        # Ventana operativa permitida: por ejemplo, de 06:00 a 23:00 hrs
        hora = v.time()
        if hora < time(6, 0) or hora > time(23, 0):
            raise ValueError("Violación normativa (RNF-02): Fuera de la ventana operativa autorizada (06:00 - 23:00 hrs).")
        return v

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
