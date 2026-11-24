from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import deps
from app.core.normative import get_normative_config
from app.models.audit import Auditoria, compute_audit_hash
from app.models.user import Usuario

router = APIRouter()


def _verify_audit_chain(records: list[Auditoria]) -> tuple[bool, int]:
    """Recorre la cadena prev_hash/hash_sha256 verificando cada registro sellado.

    Devuelve (chain_valid, sealed_records). Registros antiguos sin sellado no
    invalidan la cadena, pero sí se contabilizan aparte en la respuesta.
    """
    chain_valid = True
    sealed = 0
    last_hash: str | None = None
    for record in records:
        if record.hash_sha256 is None:
            continue
        expected_prev = last_hash
        expected_hash = compute_audit_hash(
            expected_prev,
            record.usuario_id,
            record.accion,
            record.recurso,
            record.detalle,
            record.timestamp,
        )
        if record.prev_hash != expected_prev or record.hash_sha256 != expected_hash:
            chain_valid = False
        sealed += 1
        last_hash = record.hash_sha256
    return chain_valid, sealed


@router.get("/", summary="Historial de auditoría (Solo Admin)")
def list_audit_logs(
    usuario_id: int | None = Query(None),
    accion: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    query = db.query(Auditoria)
    if usuario_id:
        query = query.filter(Auditoria.usuario_id == usuario_id)
    if accion:
        query = query.filter(Auditoria.accion == accion.upper())

    return query.order_by(Auditoria.timestamp.desc()).offset(skip).limit(limit).all()


@router.get("/export", summary="Exportar registro criptográfico de auditoría (Solo Admin)")
def export_audit_log(
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    """Devuelve el reporte firmado de auditoría: verificación de la cadena
    hash_sha256 completa, registros con el usuario asociado y resumen normativo."""
    records = db.query(Auditoria).order_by(Auditoria.id.asc()).all()
    chain_valid, sealed = _verify_audit_chain(records)
    cfg = get_normative_config()

    return {
        "sistema": "AeroLuferan - Sistema Autónomo de Vigilancia Aérea",
        "entidad": "Facultad de Informática - Universidad Autónoma de Querétaro",
        "generado_at": datetime.now(UTC).isoformat(),
        "integridad": {
            "chain_valid": chain_valid,
            "total_records": len(records),
            "sealed_records": sealed,
            "unsealed_records": len(records) - sealed,
            "algoritmo": "SHA-256 encadenado (prev_hash + contenido)",
        },
        "ventana_operativa": {
            "hora_apertura": cfg.hora_apertura,
            "hora_cierre": cfg.hora_cierre,
            "altitud_minima_m": cfg.altitud_minima_m,
            "altitud_maxima_m": cfg.altitud_maxima_m,
            "peso_maximo_kg": cfg.peso_maximo_kg,
        },
        "registros": [
            {
                "id": r.id,
                "usuario_id": r.usuario_id,
                "usuario_email": r.usuario.email if r.usuario else None,
                "usuario_rol": r.usuario.rol.nombre if r.usuario and r.usuario.rol else None,
                "accion": r.accion,
                "recurso": r.recurso,
                "detalle": r.detalle,
                "ip_origen": r.ip_origen,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "prev_hash": r.prev_hash,
                "hash_sha256": r.hash_sha256,
            }
            for r in records
        ],
    }
