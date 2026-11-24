from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.detection import Deteccion  # noqa: F401


class Evento(Base):
    __tablename__ = "eventos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tipo: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # PERSONA_NOCTURNA, PERSONA_ZONA_RESTRINGIDA, HUMO_DETECTADO
    nivel_criticidad: Mapped[str] = mapped_column(String(20), default="ALTA")  # BAJA, MEDIA, ALTA, CRITICA
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado: Mapped[str] = mapped_column(String(30), default="PENDIENTE")  # PENDIENTE, EN_REVISION, RESUELTO
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Trazabilidad de despacho y resolución operativa
    atendido_por_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)
    resuelto_por_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)
    despachado_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resuelto_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notas_resolucion: Mapped[str | None] = mapped_column(Text, nullable=True)

    detecciones: Mapped[list["Deteccion"]] = relationship("Deteccion", back_populates="evento")
