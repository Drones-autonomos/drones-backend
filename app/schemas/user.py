from datetime import datetime

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
    ) # 1 para ADMIN, 2 para GUARDIA

# Esquema de respuesta pública (sin password_hash)
class UserResponse(BaseModel):
    id: int = Field(
      ..., description="Identificador único del usuario", examples=[1]
    )
    nombre: str = Field(..., examples=["Juan Pérez"])
    email: EmailStr = Field(..., examples=["guardia@facultad.edu.mx"])
    activo: bool = Field(
      ..., description="Indica si la cuenta del usuario esta habilitada", examples=[True]
    )
    rol: RolResponse
    created_at: datetime = Field(
      ..., description="Fecha y hora de creación del usuario"
    )

    model_config = ConfigDict(from_attributes=True)
