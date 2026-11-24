from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.event import Evento


class Deteccion(Base):
    __tablename__ = "detecciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vuelo_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)  # "PERSONA", "HUMO", "EVIDENCIA_MANUAL"
    nivel_confianza: Mapped[float] = mapped_column(Float, nullable=False)
    frame_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitud: Mapped[float] = mapped_column(Numeric(10, 8), nullable=False)
    longitud: Mapped[float] = mapped_column(Numeric(11, 8), nullable=False)
    altitud_metros: Mapped[float | None] = mapped_column(Float, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    evento_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("eventos.id"), nullable=True)
    evento: Mapped["Evento | None"] = relationship("Evento", back_populates="detecciones")
