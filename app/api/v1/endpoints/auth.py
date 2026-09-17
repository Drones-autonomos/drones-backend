from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import Rol, Usuario
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserLogin, UserResponse

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Registrar usuario",
    description=(
        "Crea un nuevo usuario en el sistema con rol asignado (guardia o"
        " administrador)."
    ),
    responses={
        201: {"description": "Usuario registrado exitosamente"},
        400: {"description": "El correo electrónico ya existe en el sistema"},
        404: {"description": "El rol_id especificado no existe"},
        422: {"description": "Error de validación en los campos enviados"},
    }, ) 
def register(user_in: UserCreate, db: Session = Depends(deps.get_db)):
    """Registra un nuevo usuario con rol asignado (guardia o administrador)."""
    # 1. Verificar si el email ya existe
    user_exist = db.query(Usuario).filter(Usuario.email == user_in.email).first()
    if user_exist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El correo electrónico ya está registrado en el sistema."
        )

    # 2. Verificar que el rol_id sea válido
    rol_exist = db.query(Rol).filter(Rol.id == user_in.rol_id).first()
    if not rol_exist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El rol asignado no existe."
        )

    # 3. Crear usuario con password hasheado
    db_user = Usuario(
        nombre=user_in.nombre,
        email=user_in.email,
        password_hash=get_password_hash(user_in.password),
        rol_id=user_in.rol_id,
        activo=True
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/login", response_model=Token, response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Iniciar sesión y obtener JWT",
    description=(
        "Valida credenciales y retorna un token Bearer JWT con tiempo de"
        " expiración."
    ),
    responses={
        200: {"description": "Autenticación exitosa, token generado"},
        400: {"description": "Usuario inactivo en el sistema"},
        401: {"description": "Credenciales inválidas (correo o contraseña)"},
        422: {"description": "Formato de payload no válido"},
    },)
def login(credentials: UserLogin, db: Session = Depends(deps.get_db)):
    """Valida credenciales y entrega el Bearer JWT."""
    user = db.query(Usuario).filter(Usuario.email == credentials.email).first()
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas (correo o contraseña no válidos)."
        )
    if not user.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo en la plataforma."
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        subject=user.id, expires_delta=access_token_expires
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse, response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener perfil del usuario actual",
    description=(
        "Retorna la información del usuario autenticado a partir del Bearer"
        " Token enviado en la cabecera."
    ),
    responses={
        200: {"description": "Perfil obtenido exitosamente"},
        401: {"description": "Token inválido, expirado o ausente"},
        404: {"description": "Usuario no encontrado"},
    },)
def read_current_user(current_user: Usuario = Depends(deps.get_current_user)):
    """Retorna los datos del perfil y rol del usuario autenticado vía JWT."""
    return current_user