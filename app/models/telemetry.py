"""Modelo ORM para la bitácora transaccional de telemetría de vuelo."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class TelemetriaVuelo(Base):
    __tablename__ = "telemetria_vuelo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    mision_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("misiones.id"), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    latitud: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    longitud: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    altitud_metros: Mapped[float | None] = mapped_column(Float, nullable=True)
    bateria_porcentaje: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltaje_bateria: Mapped[float | None] = mapped_column(Float, nullable=True)
    velocidad_tierra_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    rumbo_grados: Mapped[float | None] = mapped_column(Float, nullable=True)
    modo_vuelo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    armado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    estado_enlace: Mapped[str] = mapped_column(String(30), default="OK", nullable=False)
    heartbeat_age_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    viento_velocidad_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    viento_direccion_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    satelites_gps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gps_fix_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tilt_grados: Mapped[float | None] = mapped_column(Float, nullable=True)
    senal_rf_porcentaje: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latencia_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    zona_actual: Mapped[str | None] = mapped_column(String(80), nullable=True)
    estado_zona: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failsafe_gcs_activo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
