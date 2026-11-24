import unicodedata
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.normative import (
    DEFAULT_ALTITUD_MAXIMA_M,
    validate_altitude,
    validate_operating_window,
    validate_weight,
)

ALTITUD_MAXIMA_NORMATIVA = DEFAULT_ALTITUD_MAXIMA_M
OPERATING_TZ = ZoneInfo("America/Mexico_City")
DIAS_SEMANA_VALIDOS = {"lun", "mar", "mie", "jue", "vie", "sab", "dom"}


def utc_schedule(value):
    # La columna histórica usa timestamp sin zona; todos los valores se guardan en UTC.
    if value is not None and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _validate_window_local(value):
    """Valida la ventana operativa en hora local de operación.

    Si el cliente envía un instante con zona horaria (p. ej. UTC con sufijo ``Z``
    desde ``toISOString()`` del navegador), se convierte a America/Mexico_City
    antes de comparar contra la ventana. Los timestamps naive se interpretan
    como hora local directamente (compatibilidad con clientes históricos).
    """
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if isinstance(parsed, datetime) and parsed.tzinfo is not None:
        parsed = parsed.astimezone(OPERATING_TZ).replace(tzinfo=None)
    validate_operating_window(parsed)
    return value


def _normalize_dias(value):
    if value is None:
        return None
    normalized = []
    for dia in value:
        raw = unicodedata.normalize("NFD", str(dia).strip().lower())
        code = "".join(c for c in raw if unicodedata.category(c) != "Mn")[:3]
        if not code:
            continue
        if code not in DIAS_SEMANA_VALIDOS:
            raise ValueError(
                f"Día de semana inválido: '{dia}'. Usa {sorted(DIAS_SEMANA_VALIDOS)}."
            )
        if code not in normalized:
            normalized.append(code)
    return normalized or None


class WaypointBase(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    orden_waypoint: int = Field(..., ge=1, examples=[1])
    latitud: float = Field(..., ge=-90.0, le=90.0, examples=[20.5888])
    longitud: float = Field(..., ge=-180.0, le=180.0, examples=[-100.3899])
    altitud_metros: float = Field(default=15.0, ge=2.0, le=ALTITUD_MAXIMA_NORMATIVA, examples=[15.0])
    hover_segundos: float = Field(
        default=0.0, ge=0.0, le=300.0, description="Segundos de inspección en hover sobre el punto"
    )

    @field_validator("altitud_metros")
    @classmethod
    def validar_altitud(cls, v: float) -> float:
        return validate_altitude(v)


# Alias para compatibilidad si algún módulo importa WaypointCreate
WaypointCreate = WaypointBase


class WaypointResponse(WaypointBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class MisionBase(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=100)
    descripcion: str | None = None
    horario_inicio_programado: datetime | None = None
    horario_fin_programado: datetime | None = None
    duracion_estimada_min: int | None = Field(default=None, ge=0)
    helipuerto_salida: str | None = Field(default=None, max_length=80)
    helipuerto_llegada: str | None = Field(default=None, max_length=80)
    es_recurrente: bool = False
    dias_semana: list[str] | None = None
    evitacion_exclusion: bool = True
    bateria_minima_pct: int | None = Field(default=35, ge=0, le=100)
    sensor_optico: str | None = Field(default=None, max_length=60)

    normalize_schedule = field_validator("horario_inicio_programado", "horario_fin_programado")(utc_schedule)

    @field_validator("dias_semana")
    @classmethod
    def validar_dias_semana(cls, value):
        return _normalize_dias(value)


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
        return _validate_window_local(value)

    @field_validator("waypoints")
    @classmethod
    def ordered_route(cls, value):
        if sorted(wp.orden_waypoint for wp in value) != list(range(1, len(value) + 1)):
            raise ValueError("Los waypoints deben tener órdenes únicos y consecutivos desde 1")
        return sorted(value, key=lambda wp: wp.orden_waypoint)


class MisionUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=3, max_length=100)
    descripcion: str | None = None
    horario_inicio_programado: datetime | None = None
    horario_fin_programado: datetime | None = None
    duracion_estimada_min: int | None = Field(default=None, ge=0)
    helipuerto_salida: str | None = Field(default=None, max_length=80)
    helipuerto_llegada: str | None = Field(default=None, max_length=80)
    es_recurrente: bool | None = None
    dias_semana: list[str] | None = None
    evitacion_exclusion: bool | None = None
    bateria_minima_pct: int | None = Field(default=None, ge=0, le=100)
    sensor_optico: str | None = Field(default=None, max_length=60)
    waypoints: list[WaypointBase] | None = None

    normalize_schedule = field_validator("horario_inicio_programado", "horario_fin_programado")(utc_schedule)

    @field_validator("horario_inicio_programado", mode="before")
    @classmethod
    def validar_horario_operativo(cls, value):
        if value is None:
            return None
        return _validate_window_local(value)

    @field_validator("dias_semana")
    @classmethod
    def validar_dias_semana(cls, value):
        return _normalize_dias(value)

    @field_validator("waypoints")
    @classmethod
    def ordered_route(cls, value):
        if value is None:
            return None
        if sorted(wp.orden_waypoint for wp in value) != list(range(1, len(value) + 1)):
            raise ValueError("Los waypoints deben tener órdenes únicos y consecutivos desde 1")
        return sorted(value, key=lambda wp: wp.orden_waypoint)


class MisionResponse(MisionBase):
    id: int
    creado_por: int
    ejecutado_por: int | None = None
    estado: str
    created_at: datetime
    iniciada_at: datetime | None = None
    finalizada_at: datetime | None = None
    waypoints_completados: int = 0
    error_ejecucion: str | None = None
    waypoints: list[WaypointResponse] = []

    model_config = ConfigDict(from_attributes=True)
