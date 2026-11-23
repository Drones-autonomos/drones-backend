from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api import deps
from app.models.audit import Auditoria
from app.models.user import Usuario

router = APIRouter()

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