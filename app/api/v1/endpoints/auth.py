import threading
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import Rol, Usuario
from app.schemas.token import Token
from app.schemas.user import (
    PasswordChangeRequest,
    UserCreate,
    UserLogin,
    UserPreferencesUpdate,
    UserProfileUpdate,
    UserResponse,
)

router = APIRouter()

# Dominios de correo personal no permitidos para cuentas institucionales.
# Los dominios de prueba (test.com) e institucionales (uaq.mx, facultad.edu.mx)
# permanecen válidos para no romper fixtures ni seeds existentes.
PERSONAL_EMAIL_DOMAINS = {
    "gmail.com",
    "hotmail.com",
    "hotmail.es",
    "hotmail.com.mx",
    "yahoo.com",
    "yahoo.es",
    "yahoo.com.mx",
    "outlook.com",
    "outlook.es",
    "outlook.com.mx",
    "live.com",
    "live.com.mx",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "aol.com",
}

# Protección básica contra fuerza bruta en memoria: máx. N intentos fallidos
# por correo dentro de una ventana deslizante. Solo cuentan credenciales
# rechazadas (401); un login exitoso limpia el contador.
_LOGIN_MAX_FAILURES = 10
_LOGIN_WINDOW_SECONDS = 300
_login_failures: dict[str, list[float]] = defaultdict(list)
_login_failures_lock = threading.Lock()


def _login_failure_count(email: str) -> int:
    now = time.monotonic()
    with _login_failures_lock:
        attempts = _login_failures.get(email, [])
        attempts = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
        _login_failures[email] = attempts
        return len(attempts)


def _record_login_failure(email: str) -> None:
    now = time.monotonic()
    with _login_failures_lock:
        _login_failures[email].append(now)


def _clear_login_failures(email: str) -> None:
    with _login_failures_lock:
        _login_failures.pop(email, None)


def _check_login_rate_limit(email: str) -> None:
    if _login_failure_count(email) >= _LOGIN_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Espera unos minutos antes de reintentar.",
        )


def _issue_token(user: Usuario) -> str:
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    rol_nombre = user.rol.nombre if user.rol else "GUARDIA"
    return create_access_token(subject=user.id, expires_delta=access_token_expires, rol=rol_nombre)


def _request_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar usuario",
    description=("Crea un usuario con rol asignado. Requiere ADMIN; el primer administrador se crea por CLI."),
    responses={
        201: {"description": "Usuario registrado exitosamente"},
        400: {"description": "El correo electrónico ya existe en el sistema o usa un dominio personal"},
        404: {"description": "El rol_id especificado no existe"},
        422: {"description": "Error de validación en los campos enviados"},
    },
)
def register(
    user_in: UserCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    """Registra un nuevo usuario con rol asignado (guardia o administrador)."""
    email = str(user_in.email).lower()
    domain = email.rsplit("@", 1)[-1]
    if domain in PERSONAL_EMAIL_DOMAINS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere un correo institucional; no se permiten dominios personales.",
        )

    user_exist = db.query(Usuario).filter(Usuario.email == email).first()
    if user_exist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="El correo electrónico ya está registrado en el sistema."
        )

    rol_exist = db.query(Rol).filter(Rol.id == user_in.rol_id).first()
    if not rol_exist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El rol asignado no existe.")

    db_user = Usuario(
        nombre=user_in.nombre,
        email=email,
        password_hash=get_password_hash(user_in.password),
        rol_id=user_in.rol_id,
        puesto=user_in.puesto,
        activo=True,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="CREAR_USUARIO",
        recurso="/api/v1/auth/register",
        detalle=f"Alta de {db_user.email} con rol {rol_exist.nombre} por {current_user.email}",
        ip_origen=_request_ip(request),
    )
    return db_user


@router.post(
    "/login",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Iniciar sesión y obtener JWT",
    description=("Valida credenciales y retorna un token Bearer JWT con tiempo de expiración."),
    responses={
        200: {"description": "Autenticación exitosa, token generado"},
        400: {"description": "Usuario inactivo en el sistema"},
        401: {"description": "Credenciales inválidas (correo o contraseña)"},
        403: {"description": "La cuenta no corresponde al rol seleccionado"},
        422: {"description": "Formato de payload no válido"},
        429: {"description": "Demasiados intentos fallidos"},
    },
)
def login(credentials: UserLogin, request: Request, db: Session = Depends(deps.get_db)):
    """Valida credenciales, rol esperado y rate-limiting; entrega el Bearer JWT."""
    email = str(credentials.email).lower()
    _check_login_rate_limit(email)

    user = db.query(Usuario).filter(Usuario.email == email).first()
    if not user or not verify_password(credentials.password, user.password_hash):
        _record_login_failure(email)
        deps.log_audit_event(
            db,
            usuario_id=None,
            accion="LOGIN_FALLIDO",
            recurso="/api/v1/auth/login",
            detalle=f"Credenciales rechazadas para {email}",
            ip_origen=_request_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas (correo o contraseña no válidos).",
        )
    if not user.activo:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Usuario inactivo en la plataforma.")

    real_role = (user.rol.nombre if user.rol else "GUARDIA").upper()
    if credentials.expected_role and credentials.expected_role.upper() != real_role:
        deps.log_audit_event(
            db,
            usuario_id=user.id,
            accion="LOGIN_ROL_INCORRECTO",
            recurso="/api/v1/auth/login",
            detalle=f"Rol esperado {credentials.expected_role.upper()}, rol real {real_role}",
            ip_origen=_request_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Esta cuenta pertenece al rol {real_role}. "
                "Selecciona la tarjeta de acceso correspondiente."
            ),
        )

    _clear_login_failures(email)
    deps.log_audit_event(
        db,
        usuario_id=user.id,
        accion="LOGIN",
        recurso="/api/v1/auth/login",
        detalle=f"Inicio de sesión de {user.email}",
        ip_origen=_request_ip(request),
    )
    return {"access_token": _issue_token(user), "token_type": "bearer"}


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener perfil del usuario actual",
    description=("Retorna la información del usuario autenticado a partir del Bearer Token enviado en la cabecera."),
    responses={
        200: {"description": "Perfil obtenido exitosamente"},
        401: {"description": "Token inválido, expirado o ausente"},
        404: {"description": "Usuario no encontrado"},
    },
)
def read_current_user(current_user: Usuario = Depends(deps.get_current_user)):
    """Retorna los datos del perfil y rol del usuario autenticado vía JWT."""
    return current_user


@router.patch(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar perfil propio",
    description="Persiste nombre, puesto y fotografía del usuario autenticado.",
)
def update_current_user(
    payload: UserProfileUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.get_current_user),
):
    """Actualiza el perfil del usuario autenticado (ADMIN o GUARDIA)."""
    if payload.nombre is not None:
        current_user.nombre = payload.nombre
    if payload.puesto is not None:
        current_user.puesto = payload.puesto
    if payload.foto_url is not None:
        foto = payload.foto_url
        is_data_url = foto.startswith("data:image/")
        is_http_url = foto.startswith("http://") or foto.startswith("https://")
        if foto and not (is_data_url or is_http_url):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="foto_url debe ser una Data URL de imagen (data:image/...) o una URL http(s).",
            )
        if len(foto) > 2_800_000:  # ~2 MB codificados en base64
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La fotografía excede el tamaño máximo permitido (2 MB).",
            )
        current_user.foto_url = foto or None
    db.commit()
    db.refresh(current_user)
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="ACTUALIZAR_PERFIL",
        recurso="/api/v1/auth/me",
        detalle="Actualización de nombre/puesto/foto propios",
        ip_origen=_request_ip(request),
    )
    return current_user


@router.patch(
    "/me/preferences",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar preferencias personales",
    description="Guarda preferencias por usuario (push críticas, calidad de transmisión).",
)
def update_current_user_preferences(
    payload: UserPreferencesUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.get_current_user),
):
    """Persiste preferencias personales en Usuario.preferencias_json."""
    prefs = dict(current_user.preferencias or {})
    if payload.critical_push_enabled is not None:
        prefs["critical_push_enabled"] = payload.critical_push_enabled
    if payload.transmission_quality_id is not None:
        prefs["transmission_quality_id"] = payload.transmission_quality_id
    current_user.preferencias = prefs
    db.commit()
    db.refresh(current_user)
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="ACTUALIZAR_PREFERENCIAS",
        recurso="/api/v1/auth/me/preferences",
        detalle=f"Preferencias actualizadas: {sorted(prefs.keys())}",
        ip_origen=_request_ip(request),
    )
    return current_user


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Cambiar contraseña propia",
    description="Verifica la contraseña actual y la reemplaza; revoca el token en uso.",
)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.get_current_user),
    token: str = Depends(deps.reusable_oauth2),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual no coincide.",
        )
    current_user.password_hash = get_password_hash(payload.new_password)
    # Marca de corte global: además del jti actual, cualquier otra sesión del
    # usuario emitida antes de este instante queda invalidada.
    current_user.tokens_invalidados_antes_de = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    deps.revoke_token(db, deps.decode_token_payload(token))
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="CAMBIAR_PASSWORD",
        recurso="/api/v1/auth/change-password",
        detalle="Contraseña propia actualizada; token previo revocado",
        ip_origen=_request_ip(request),
    )
    return {"detail": "Contraseña actualizada. Inicia sesión nuevamente."}


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Cerrar sesión (revocar JWT)",
    description="Revoca el jti del token actual para invalidarlo en todo el sistema.",
)
def logout(
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.get_current_user),
    token: str = Depends(deps.reusable_oauth2),
):
    deps.revoke_token(db, deps.decode_token_payload(token))
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="LOGOUT",
        recurso="/api/v1/auth/logout",
        detalle=f"Cierre de sesión de {current_user.email}",
        ip_origen=_request_ip(request),
    )
    return {"detail": "Sesión cerrada correctamente."}


@router.post(
    "/refresh",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Renovar token JWT",
    description="Emite un nuevo JWT y revoca el token anterior.",
)
def refresh_token(
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.get_current_user),
    token: str = Depends(deps.reusable_oauth2),
):
    deps.revoke_token(db, deps.decode_token_payload(token))
    return {"access_token": _issue_token(current_user), "token_type": "bearer"}
