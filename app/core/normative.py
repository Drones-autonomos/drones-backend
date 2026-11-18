"""Configuración y validaciones normativas compartidas para misiones y control de vuelo."""

import math
from datetime import datetime, time

from pydantic import BaseModel, Field

DEFAULT_ALTITUD_MAXIMA_M = 200.0
DEFAULT_ALTITUD_MINIMA_M = 2.0
DEFAULT_PESO_MAXIMO_KG = 5.0
DEFAULT_HORA_APERTURA = "06:00"
DEFAULT_HORA_CIERRE = "23:00"


class NormativeConfig(BaseModel):
    altitud_minima_m: float = Field(default=DEFAULT_ALTITUD_MINIMA_M, ge=1.0, le=50.0)
    altitud_maxima_m: float = Field(default=DEFAULT_ALTITUD_MAXIMA_M, ge=2.0, le=200.0)
    peso_maximo_kg: float = Field(default=DEFAULT_PESO_MAXIMO_KG, gt=0.0, le=25.0)
    hora_apertura: str = DEFAULT_HORA_APERTURA
    hora_cierre: str = DEFAULT_HORA_CIERRE


_current_config = NormativeConfig()


def get_normative_config() -> NormativeConfig:
    return _current_config


def update_normative_config(new_config: NormativeConfig) -> NormativeConfig:
    global _current_config
    _current_config = new_config
    return _current_config


def _parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    return time(int(parts[0]), int(parts[1]))


def validate_altitude(altitude_m: float, config: NormativeConfig | None = None) -> float:
    cfg = config or get_normative_config()
    if not math.isfinite(altitude_m) or altitude_m < cfg.altitud_minima_m or altitude_m > cfg.altitud_maxima_m:
        raise ValueError(
            f"Violación normativa (RNF-07): Altitud fuera de rango "
            f"({cfg.altitud_minima_m}–{cfg.altitud_maxima_m} m). Recibido: {altitude_m} m."
        )
    return altitude_m


def validate_weight(weight_kg: float, config: NormativeConfig | None = None) -> float:
    cfg = config or get_normative_config()
    if not math.isfinite(weight_kg) or weight_kg <= 0 or weight_kg > cfg.peso_maximo_kg:
        raise ValueError(
            f"Violación normativa: El peso ({weight_kg} kg) excede el límite permitido de {cfg.peso_maximo_kg} kg."
        )
    return weight_kg


def validate_operating_window(moment: datetime, config: NormativeConfig | None = None) -> datetime:
    cfg = config or get_normative_config()
    apertura = _parse_hhmm(cfg.hora_apertura)
    cierre = _parse_hhmm(cfg.hora_cierre)
    hora = moment.time()
    if hora < apertura or hora > cierre:
        raise ValueError(
            f"Violación normativa (RNF-02): Fuera de la ventana operativa autorizada "
            f"({cfg.hora_apertura} - {cfg.hora_cierre} hrs)."
        )
    return moment
