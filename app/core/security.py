from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

# contexto de hashing para contraseñas using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# verifica si la contrasena plana coincide con el hash almacenado
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# hashea la contrasena plana
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# firma un token de acceso con un sujeto sea id o email y una fecha de expiración
def create_access_token(subject: str | int, expires_delta: timedelta | None = None, rol: str | None = None) -> str:
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "exp": expire,
        "iat": datetime.now(UTC),
        "sub": str(subject),
        "jti": uuid4().hex,
    }
    if rol:
        to_encode["rol"] = rol
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt
