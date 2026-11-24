from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.audit import Auditoria
from app.models.user import TokenRevocado, Usuario
from app.schemas.token import TokenPayload

# Define que la URL de obtención de token es /api/v1/auth/login
reusable_oauth2 = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def log_audit_event(
    db: Session,
    usuario_id: int | None,
    accion: str,
    recurso: str,
    detalle: str | None = None,
    ip_origen: str | None = None,
) -> None:
    """Inserta un registro sellado en `auditoria` sin romper el flujo del endpoint."""
    try:
        registro = Auditoria(
            usuario_id=usuario_id,
            accion=accion,
            recurso=recurso,
            detalle=detalle,
            ip_origen=ip_origen,
        )
        db.add(registro)
        db.commit()
    except SQLAlchemyError:
        db.rollback()


def audit_action(accion: str):
    def _logger(
        request: Request,
        db: Session = Depends(get_db),
        current_user: Usuario = Depends(get_current_user),
    ):
        log_audit_event(
            db,
            usuario_id=current_user.id,
            accion=accion,
            recurso=str(request.url.path),
            detalle=f"Método {request.method} ejecutado por {current_user.email}",
            ip_origen=request.client.host if request.client else "unknown",
        )
        return current_user
    return _logger


def get_db() -> Generator[Session, None, None]:
    """Crea una sesión de base de datos por petición y la cierra al finalizar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales de autenticación",
        headers={"WWW-Authenticate": "Bearer"},
    )


def decode_token_payload(token: str) -> dict:
    """Decodifica y valida la firma/expiración del JWT. Lanza 401 si es inválido."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise _credentials_exception() from exc


def is_token_revoked(db: Session, jti: str | None) -> bool:
    """True si el jti del token figura en la lista de revocación."""
    if not jti:
        return False
    try:
        return db.query(TokenRevocado).filter(TokenRevocado.jti == jti).first() is not None
    except SQLAlchemyError:
        # Tabla aún no migrada en este entorno: no bloquear la autenticación.
        return False


def revoke_token(db: Session, payload: dict) -> None:
    """Registra el jti del token en la lista de revocación (best-effort)."""
    jti = payload.get("jti")
    if not jti:
        return
    from datetime import UTC, datetime

    expira_at = datetime.fromtimestamp(payload.get("exp", 0), UTC)
    try:
        if not db.query(TokenRevocado).filter(TokenRevocado.jti == jti).first():
            db.add(TokenRevocado(jti=jti, expira_at=expira_at.replace(tzinfo=None)))
            # Limpieza oportunista de revocaciones ya expiradas.
            db.query(TokenRevocado).filter(TokenRevocado.expira_at < datetime.now(UTC).replace(tzinfo=None)).delete()
            db.commit()
    except SQLAlchemyError:
        db.rollback()


def _user_from_payload(db: Session, payload: dict) -> Usuario:
    credentials_exception = _credentials_exception()
    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    token_data = TokenPayload(sub=user_id)

    if is_token_revoked(db, payload.get("jti")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión revocada. Inicia sesión nuevamente.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(Usuario).filter(Usuario.id == int(token_data.sub)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    if not user.activo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Usuario inactivo")
    if user.tokens_invalidados_antes_de is not None:
        from datetime import UTC

        cutoff = user.tokens_invalidados_antes_de.replace(tzinfo=UTC).timestamp()
        if float(payload.get("iat") or 0) < cutoff:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sesión invalidada. Inicia sesión nuevamente.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return user


def get_current_user(db: Session = Depends(get_db), token: str = Depends(reusable_oauth2)) -> Usuario:
    """Valida el token JWT (Bearer) y extrae al usuario autenticado de la base de datos."""
    payload = decode_token_payload(token)
    return _user_from_payload(db, payload)


def get_current_user_ws_or_query(db: Session, token: str) -> Usuario:
    """Autentica un token JWT recibido fuera del header Authorization.

    Pensado para endpoints que aceptan `?token=` (streams, websockets) donde el
    navegador no puede adjuntar cabeceras. Mismas validaciones que
    `get_current_user` (firma, expiración, revocación jti, usuario activo).
    """
    payload = decode_token_payload(token)
    return _user_from_payload(db, payload)


def validate_ws_token(
    db: Session,
    raw_token: str,
    allowed_roles: tuple[str, ...] = ("ADMIN", "GUARDIA"),
) -> Usuario | None:
    """Valida un JWT recibido por WebSocket (`?token=` o subprotocolo).

    Devuelve el `Usuario` autenticado o `None` cuando el token es inválido,
    está revocado (jti en `tokens_revocados`), el usuario está inactivo o su
    rol no está en `allowed_roles`. Pensado para que los endpoints WS decidan
    cerrar con `WS_1008_POLICY_VIOLATION` sin levantar excepciones HTTP.
    """
    if not raw_token:
        return None
    try:
        payload = decode_token_payload(raw_token)
        user = _user_from_payload(db, payload)
    except HTTPException:
        return None
    if allowed_roles and (not user.rol or user.rol.nombre not in allowed_roles):
        return None
    return user


# control de acceso basado en roles RBAC


class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: Usuario = Depends(get_current_user)) -> Usuario:
        if not current_user.rol or current_user.rol.nombre not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operación no permitida para el rol asignado.",
            )
        return current_user


# Dependencias exportadas para los endpoints
require_admin = RoleChecker(["ADMIN"])
require_guard_or_admin = RoleChecker(["ADMIN", "GUARDIA"])
