"""Endpoints de administración de usuarios (solo ADMIN)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api import deps
from app.core.security import get_password_hash
from app.models.user import Rol, Usuario
from app.schemas.user import AdminPasswordReset, AdminUserUpdate, RolResponse, UserResponse

router = APIRouter()


def _request_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _count_active_admins(db: Session) -> int:
    return (
        db.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(Rol.nombre == "ADMIN", Usuario.activo.is_(True))
        .count()
    )


def _is_last_active_admin(db: Session, target: Usuario) -> bool:
    return (
        target.rol is not None
        and target.rol.nombre == "ADMIN"
        and target.activo
        and _count_active_admins(db) <= 1
    )


@router.get(
    "/",
    response_model=list[UserResponse],
    summary="Listar usuarios",
    description="Lista los usuarios reales de la base de datos con filtros opcionales.",
)
def list_users(
    q: str | None = Query(None, description="Búsqueda por nombre o correo"),
    rol_id: int | None = Query(None),
    activo: bool | None = Query(None),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    query = db.query(Usuario)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter((Usuario.nombre.ilike(term)) | (Usuario.email.ilike(term)))
    if rol_id is not None:
        query = query.filter(Usuario.rol_id == rol_id)
    if activo is not None:
        query = query.filter(Usuario.activo.is_(activo))
    return query.order_by(Usuario.created_at.desc()).all()


@router.get(
    "/roles",
    response_model=list[RolResponse],
    summary="Listar roles disponibles",
)
def list_roles(
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    return db.query(Rol).order_by(Rol.id).all()


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Actualizar usuario",
    description="Edita nombre, puesto, rol y estado activo. Protege al último administrador activo.",
)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    target = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")

    new_rol = None
    if payload.rol_id is not None:
        new_rol = db.query(Rol).filter(Rol.id == payload.rol_id).first()
        if not new_rol:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El rol asignado no existe.")

    demotes_admin = new_rol is not None and new_rol.nombre != "ADMIN"
    deactivates = payload.activo is False
    if (demotes_admin or deactivates) and _is_last_active_admin(db, target):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede degradar ni desactivar al único administrador activo del sistema.",
        )

    if payload.nombre is not None:
        target.nombre = payload.nombre
    if payload.puesto is not None:
        target.puesto = payload.puesto
    if new_rol is not None:
        target.rol_id = new_rol.id
    if payload.activo is not None:
        target.activo = payload.activo
        if payload.activo is False:
            # Desactivación: invalida de inmediato todos los tokens del usuario.
            target.tokens_invalidados_antes_de = datetime.now(UTC).replace(tzinfo=None)

    db.commit()
    db.refresh(target)
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="ACTUALIZAR_USUARIO",
        recurso=f"/api/v1/users/{user_id}",
        detalle=f"Admin {current_user.email} actualizó a {target.email}",
        ip_origen=_request_ip(request),
    )
    return target


@router.post(
    "/{user_id}/reset-password",
    summary="Restablecer contraseña de usuario",
    description="Asigna una nueva contraseña al usuario indicado (solo ADMIN).",
)
def reset_user_password(
    user_id: int,
    payload: AdminPasswordReset,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    target = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")

    target.password_hash = get_password_hash(payload.new_password)
    # Reset administrativo: revoca todas las sesiones abiertas del usuario.
    target.tokens_invalidados_antes_de = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="RESTABLECER_PASSWORD",
        recurso=f"/api/v1/users/{user_id}/reset-password",
        detalle=f"Admin {current_user.email} restableció la contraseña de {target.email}",
        ip_origen=_request_ip(request),
    )
    return {"detail": f"Contraseña de {target.email} restablecida."}


@router.delete(
    "/{user_id}",
    summary="Dar de baja usuario",
    description="Desactiva la cuenta (baja lógica). No permite auto-eliminación.",
)
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar tu propia cuenta en sesión.",
        )
    target = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    if _is_last_active_admin(db, target):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede dar de baja al único administrador activo del sistema.",
        )

    target.activo = False
    target.tokens_invalidados_antes_de = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="BAJA_USUARIO",
        recurso=f"/api/v1/users/{user_id}",
        detalle=f"Admin {current_user.email} dio de baja a {target.email}",
        ip_origen=_request_ip(request),
    )
    return {"detail": f"Usuario {target.email} desactivado.", "activo": False}
