"""Modelo ORM para geocercas operativas (circulares o poligonales)."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class Geocerca(Base):
    __tablename__ = "geocercas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # CIRCULAR | POLIGONO
    activa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    centro_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    centro_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    radio_metros: Mapped[float | None] = mapped_column(Float, nullable=True)
    poligono_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    altitud_min_m: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    altitud_max_m: Mapped[float] = mapped_column(Float, default=200.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
