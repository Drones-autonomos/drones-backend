from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base
from app.models.event import Evento

class Alerta(Base):
    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    evento_id: Mapped[int] = mapped_column(Integer, ForeignKey("eventos.id"), nullable=False)
    titulo: Mapped[str] = mapped_column(String(100), nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    nivel_criticidad: Mapped[str] = mapped_column(String(20), default="ALTA")
    leida: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    destinatario_rol: Mapped[str] = mapped_column(String(30), default="GUARDIA")
    timestamp_envio: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    evento: Mapped["Evento"] = relationship("Evento", backref="alertas")