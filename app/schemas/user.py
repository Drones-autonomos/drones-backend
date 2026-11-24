from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RolBase(BaseModel):
    nombre: str = Field(
        ...,
        description="Nombre del rol en el sistema",
        examples=["ADMIN", "GUARDIA"],
    )
    descripcion: str | None = Field(
        None,
        description="Descripción de los permisos del rol",
        examples=["Guardia de vigilancia de la facultad"],
    )


class RolResponse(RolBase):
    id: int = Field(..., description="Identificador único del rol", examples=[2])
    model_config = ConfigDict(from_attributes=True)


# Esquema para login
class UserLogin(BaseModel):
    email: EmailStr = Field(
        ...,
        description="Correo electrónico institucional",
        examples=["guardia@facultad.edu.mx"],
    )
    password: str = Field(
        ...,
        min_length=6,
        description="Contraseña de acceso del usuario",
        examples=["PasswordSegura123!"],
    )
    expected_role: Literal["ADMIN", "GUARDIA"] | None = Field(
        default=None,
        description=(
            "Rol esperado seleccionado en la pantalla de acceso; si se envía y no "
            "coincide con el rol real de la cuenta, la API responde 403."
        ),
        examples=["GUARDIA"],
    )


# Esquema para registro
class UserCreate(BaseModel):
    nombre: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Nombre completo del usuario",
        examples=["Juan Pérez"],
    )
    email: EmailStr = Field(
        ...,
        description="Correo electrónico para registro",
        examples=["guardia@facultad.edu.mx"],
    )
    password: str = Field(
        ...,
        min_length=6,
        description="Contraseña de al menos 6 caracteres",
        examples=["PasswordSegura123!"],
    )
    rol_id: int = Field(
        ...,
        description="ID del rol asignado (1: ADMIN, 2: GUARDIA)",
        examples=[2],
    )  # 1 para ADMIN, 2 para GUARDIA
    puesto: str | None = Field(
        None,
        max_length=100,
        description="Cargo o puesto institucional opcional",
        examples=["Guardia Supervisor"],
    )


# Esquema de respuesta pública (sin password_hash)
class UserResponse(BaseModel):
    id: int = Field(..., description="Identificador único del usuario", examples=[1])
    nombre: str = Field(..., examples=["Juan Pérez"])
    email: EmailStr = Field(..., examples=["guardia@facultad.edu.mx"])
    puesto: str | None = Field(None, description="Cargo o puesto institucional", examples=["Guardia Supervisor"])
    foto_url: str | None = Field(None, description="Fotografía de perfil (Data URL o URL)")
    preferencias: dict | None = Field(
        None,
        description="Preferencias personales persistidas (push críticas, calidad de transmisión)",
        examples=[{"critical_push_enabled": True, "transmission_quality_id": "fhd-60"}],
    )
    activo: bool = Field(..., description="Indica si la cuenta del usuario esta habilitada", examples=[True])
    rol: RolResponse
    created_at: datetime = Field(..., description="Fecha y hora de creación del usuario")

    model_config = ConfigDict(from_attributes=True)


# Actualización del perfil propio (PATCH /auth/me)
class UserProfileUpdate(BaseModel):
    nombre: str | None = Field(None, min_length=2, max_length=100, examples=["Juan Pérez"])
    puesto: str | None = Field(None, max_length=100, examples=["Guardia Supervisor"])
    foto_url: str | None = Field(
        None,
        description="Data URL base64 (<= 2 MB) o URL http(s) de la fotografía de perfil",
    )


# Preferencias personales por usuario (PATCH /auth/me/preferences)
class UserPreferencesUpdate(BaseModel):
    critical_push_enabled: bool | None = None
    transmission_quality_id: Literal["fhd-60", "4k-30", "hd-30"] | None = None


# Cambio de contraseña propio (POST /auth/change-password)
class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)


# Actualización administrativa de un usuario (PATCH /users/{id})
class AdminUserUpdate(BaseModel):
    nombre: str | None = Field(None, min_length=2, max_length=100)
    puesto: str | None = Field(None, max_length=100)
    rol_id: int | None = None
    activo: bool | None = None


# Restablecer contraseña de otro usuario (POST /users/{id}/reset-password)
class AdminPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=6)
