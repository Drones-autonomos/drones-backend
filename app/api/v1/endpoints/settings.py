"""Endpoints para consultar y actualizar la configuración normativa operativa."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api import deps
from app.core.normative import NormativeConfig, get_normative_config, update_normative_config
from app.models.user import Usuario


router = APIRouter()

class NormativeConfig(BaseModel):
    altitud_maxima_m: float = 200.0
    peso_maximo_kg: float = 5.0
    hora_apertura: str = "00:00"
    hora_cierre: str = "23:59"

CONFIG_ACTUAL = NormativeConfig()

@router.get("/operating-window", response_model=NormativeConfig)
def get_operating_window(current_user: Usuario = Depends(deps.require_guard_or_admin)):
    return get_normative_config()


@router.put("/operating-window", response_model=NormativeConfig)
def update_operating_window(
    new_config: NormativeConfig,
    current_user: Usuario = Depends(deps.require_admin),
):
    return update_normative_config(new_config)
