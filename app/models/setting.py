"""Modelo ORM para los ajustes operativos persistidos (fila única de configuración)."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class AjustesOperativos(Base):
    """Fila única (singleton) con los ajustes operativos del módulo Ajustes.

    El frontend guarda además caché en localStorage; esta tabla es la fuente
    de verdad compartida entre sesiones y dispositivos.
    """

    __tablename__ = "ajustes_operativos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    critical_push_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ai_sensitivity_id: Mapped[str] = mapped_column(String(10), default="95", nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    transmission_quality_id: Mapped[str] = mapped_column(
        String(20), default="fhd-60", nullable=False
    )
    # Ventana operativa normativa persistida (fuente de verdad para
    # app.core.normative; se sincroniza a _current_config en cada GET/PUT).
    altitud_minima_m: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    altitud_maxima_m: Mapped[float] = mapped_column(Float, default=200.0, nullable=False)
    peso_maximo_kg: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    hora_apertura: Mapped[str] = mapped_column(String(5), default="06:00", nullable=False)
    hora_cierre: Mapped[str] = mapped_column(String(5), default="23:00", nullable=False)
    # Estado persistido del planificador autónomo de misiones; Agente 3 lo
    # escribe desde PUT /missions/scheduler y el lifespan lo restaura al arrancar.
    scheduler_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
