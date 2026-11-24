"""Modelo ORM para estaciones de carga/helipuertos del campus."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class EstacionCarga(Base):
    __tablename__ = "estaciones_carga"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    latitud: Mapped[float] = mapped_column(Float, nullable=False)
    longitud: Mapped[float] = mapped_column(Float, nullable=False)
    dock_radius_m: Mapped[float] = mapped_column(Float, default=3.0, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), default="IDLE", nullable=False)
    domo_estado: Mapped[str] = mapped_column(String(20), default="Abierto", nullable=False)
    voltaje_pad_v: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperatura_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    bateria_porcentaje: Mapped[float | None] = mapped_column(Float, nullable=True)
    ciclos_completados: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ultimo_acoplamiento_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
