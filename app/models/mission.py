import json
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
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

    # Metadatos operativos y de programación
    ejecutado_por: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)
    horario_fin_programado: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duracion_estimada_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    helipuerto_salida: Mapped[str | None] = mapped_column(String(80), nullable=True)
    helipuerto_llegada: Mapped[str | None] = mapped_column(String(80), nullable=True)
    es_recurrente: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dias_semana_json: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evitacion_exclusion: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    bateria_minima_pct: Mapped[int | None] = mapped_column(Integer, nullable=True, default=35)
    sensor_optico: Mapped[str | None] = mapped_column(String(60), nullable=True)

    @property
    def dias_semana(self) -> list[str] | None:
        if not self.dias_semana_json:
            return None
        try:
            parsed = json.loads(self.dias_semana_json)
        except (TypeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, list) else None

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
    hover_segundos: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    mision: Mapped["Mision"] = relationship("Mision", back_populates="waypoints")
