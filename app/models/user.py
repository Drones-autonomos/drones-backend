import json
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

# Tabla asociativa Rol <-> Permiso
rol_permiso = Table(
    "roles_permisos",
    Base.metadata,
    Column("rol_id", Integer, ForeignKey("roles.id"), primary_key=True),
    Column("permiso_id", Integer, ForeignKey("permisos.id"), primary_key=True),
)


class Permiso(Base):
    __tablename__ = "permisos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )  # ej: "misiones:crear", "misiones:cancelar"
    descripcion: Mapped[str] = mapped_column(String(255), nullable=True)

    roles: Mapped[list["Rol"]] = relationship("Rol", secondary=rol_permiso, back_populates="permisos")


class Rol(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # 'ADMIN', 'GUARDIA'
    descripcion: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    usuarios: Mapped[list["Usuario"]] = relationship("Usuario", back_populates="rol")
    permisos: Mapped[list["Permiso"]] = relationship("Permiso", secondary=rol_permiso, back_populates="roles")


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rol_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    puesto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    foto_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferencias_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Corte de validez para todos los tokens previos del usuario: tokens con
    # `iat` anterior a este instante se rechazan aunque no estén expirados
    # (desactivación de cuenta o restablecimiento de contraseña por ADMIN).
    tokens_invalidados_antes_de: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    rol: Mapped["Rol"] = relationship("Rol", back_populates="usuarios")

    @property
    def preferencias(self) -> dict | None:
        """Preferencias personales del usuario decodificadas desde preferencias_json."""
        if not self.preferencias_json:
            return None
        try:
            parsed = json.loads(self.preferencias_json)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @preferencias.setter
    def preferencias(self, value: dict | None) -> None:
        self.preferencias_json = json.dumps(value) if value else None


class TokenRevocado(Base):
    """JTIs de tokens JWT revocados (logout / refresh / cambio de contraseña)."""

    __tablename__ = "tokens_revocados"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expira_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revocado_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
