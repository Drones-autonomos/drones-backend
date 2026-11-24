"""Endpoints para consultar y actualizar la configuración normativa operativa."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api import deps
from app.core.normative import (
    DEFAULT_ALTITUD_MAXIMA_M,
    DEFAULT_ALTITUD_MINIMA_M,
    DEFAULT_HORA_APERTURA,
    DEFAULT_HORA_CIERRE,
    DEFAULT_PESO_MAXIMO_KG,
    NormativeConfig,
    get_normative_config,
    update_normative_config,
)
from app.models.setting import AjustesOperativos
from app.models.user import Usuario

router = APIRouter()


def _request_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _get_settings_row(db: Session) -> AjustesOperativos | None:
    """Devuelve la fila única de ajustes operativos (o None si aún no existe)."""
    return db.query(AjustesOperativos).order_by(AjustesOperativos.id).first()


def _get_or_create_settings_row(db: Session) -> AjustesOperativos:
    row = _get_settings_row(db)
    if row is None:
        row = AjustesOperativos()
        db.add(row)
        db.flush()
    return row


def _normative_from_row(row: AjustesOperativos) -> NormativeConfig:
    return NormativeConfig(
        altitud_minima_m=row.altitud_minima_m or DEFAULT_ALTITUD_MINIMA_M,
        altitud_maxima_m=row.altitud_maxima_m or DEFAULT_ALTITUD_MAXIMA_M,
        peso_maximo_kg=row.peso_maximo_kg or DEFAULT_PESO_MAXIMO_KG,
        hora_apertura=row.hora_apertura or DEFAULT_HORA_APERTURA,
        hora_cierre=row.hora_cierre or DEFAULT_HORA_CIERRE,
    )


def _sync_normative_from_db(db: Session) -> NormativeConfig:
    """Lee la ventana persistida en ajustes_operativos y refresca _current_config."""
    row = _get_settings_row(db)
    if row is None:
        return get_normative_config()
    return update_normative_config(_normative_from_row(row))


def hydrate_runtime_settings_from_db(db: Session) -> None:
    """Hidrata la configuración en RAM desde `ajustes_operativos` al arrancar.

    Carga la fila singleton (creándola con defaults si no existe) y sincroniza
    `app.core.normative._current_config`. La invoca `app.main` (lifespan) para
    que el backend arranque con la ventana operativa persistida en lugar de los
    defaults de fábrica. Falla silenciosamente en entornos sin la tabla aún
    migrada (tests en memoria la crean vía metadata).
    """
    try:
        row = _get_or_create_settings_row(db)
        db.commit()
        update_normative_config(_normative_from_row(row))
    except Exception:
        db.rollback()


@router.get("/operating-window", response_model=NormativeConfig)
def get_operating_window(
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    """Devuelve la ventana operativa persistida en BD (y sincroniza el caché global)."""
    return _sync_normative_from_db(db)


@router.put("/operating-window", response_model=NormativeConfig)
def update_operating_window(
    new_config: NormativeConfig,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    """Persiste la ventana normativa en ajustes_operativos y actualiza el caché global."""
    row = _get_or_create_settings_row(db)
    row.altitud_minima_m = new_config.altitud_minima_m
    row.altitud_maxima_m = new_config.altitud_maxima_m
    row.peso_maximo_kg = new_config.peso_maximo_kg
    row.hora_apertura = new_config.hora_apertura
    row.hora_cierre = new_config.hora_cierre
    db.commit()

    applied = update_normative_config(new_config)
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="ACTUALIZAR_VENTANA_OPERATIVA",
        recurso="/api/v1/settings/operating-window",
        detalle=(
            f"Ventana {new_config.hora_apertura}-{new_config.hora_cierre} · "
            f"{new_config.altitud_minima_m}-{new_config.altitud_maxima_m} m · "
            f"{new_config.peso_maximo_kg} kg"
        ),
        ip_origen=_request_ip(request),
    )
    return applied


class OperatorSettings(BaseModel):
    """Ajustes operativos del módulo Ajustes (persistidos en ajustes_operativos).

    Los enumerados replican las opciones del frontend (ajustesData.js):
    sensibilidad IA 90|95|98, retención 30|60|90 días y calidad de
    transmisión fhd-60|4k-30|hd-30.
    """

    critical_push_enabled: bool = True
    ai_sensitivity_id: Literal["90", "95", "98"] = "95"
    retention_days: Literal[30, 60, 90] = 30
    transmission_quality_id: Literal["fhd-60", "4k-30", "hd-30"] = "fhd-60"

    model_config = ConfigDict(from_attributes=True)


@router.get("/operator", response_model=OperatorSettings)
def get_operator_settings(
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    """Lee los ajustes operativos persistidos; devuelve defaults si no hay fila."""
    row = _get_settings_row(db)
    if row is None:
        return OperatorSettings()
    return row


@router.put("/operator", response_model=OperatorSettings)
def update_operator_settings(
    new_settings: OperatorSettings,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    """Actualiza la fila única de ajustes operativos (solo ADMIN)."""
    row = _get_or_create_settings_row(db)
    row.critical_push_enabled = new_settings.critical_push_enabled
    row.ai_sensitivity_id = new_settings.ai_sensitivity_id
    row.retention_days = new_settings.retention_days
    row.transmission_quality_id = new_settings.transmission_quality_id
    db.commit()
    db.refresh(row)
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="ACTUALIZAR_AJUSTES_OPERATIVOS",
        recurso="/api/v1/settings/operator",
        detalle=(
            f"push={new_settings.critical_push_enabled} ia={new_settings.ai_sensitivity_id} "
            f"retencion={new_settings.retention_days}d calidad={new_settings.transmission_quality_id}"
        ),
        ip_origen=_request_ip(request),
    )
    return row
