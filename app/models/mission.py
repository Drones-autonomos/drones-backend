from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class Mision(Base):
    __tablename__ = "misiones"
    __table_args__ = (CheckConstraint("vehiculo_activo IS NULL OR vehiculo_activo = 1", name="ck_mision_vehiculo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    creado_por: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=True)
    estado: Mapped[str] = mapped_column(
        String(30), default="PROGRAMADA", nullable=False
    )  # PROGRAMADA, EN_CURSO, CANCELANDO, FINALIZADA, CANCELADA, FALLIDA, RECUPERACION
    horario_inicio_programado: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    iniciada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalizada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    waypoints_completados: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_ejecucion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Una única reserva persistente para el vehículo, incluso tras reiniciar la API.
    vehiculo_activo: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)

    # Relaciones
    waypoints: Mapped[list["Ruta"]] = relationship(
        "Ruta",
        back_populates="mision",
        cascade="all, delete-orphan",
        order_by="Ruta.orden_waypoint",
    )


class Ruta(Base):
    __tablename__ = "rutas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    mision_id: Mapped[int] = mapped_column(Integer, ForeignKey("misiones.id"), nullable=False)
    orden_waypoint: Mapped[int] = mapped_column(Integer, nullable=False)
    latitud: Mapped[float] = mapped_column(Numeric(10, 8), nullable=False)
    longitud: Mapped[float] = mapped_column(Numeric(11, 8), nullable=False)
    altitud_metros: Mapped[float] = mapped_column(Float, default=15.0)

    mision: Mapped["Mision"] = relationship("Mision", back_populates="waypoints")
