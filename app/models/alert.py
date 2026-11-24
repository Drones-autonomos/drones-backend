from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    destinatario_rol: Mapped[str] = mapped_column(String(30), default="TODOS")
    timestamp_envio: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    evento: Mapped["Evento"] = relationship("Evento", backref="alertas")
    estados_usuario: Mapped[list["AlertaUsuario"]] = relationship(
        "AlertaUsuario",
        back_populates="alerta",
        cascade="all, delete-orphan",
    )


class AlertaUsuario(Base):
    """Estado individual de lectura y descarte de una alerta por usuario."""

    __tablename__ = "alertas_usuarios"
    __table_args__ = (UniqueConstraint("usuario_id", "alerta_id", name="uq_alerta_usuario"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    alerta_id: Mapped[int] = mapped_column(Integer, ForeignKey("alertas.id"), nullable=False, index=True)
    leida_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    descartada_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    alerta: Mapped["Alerta"] = relationship("Alerta", back_populates="estados_usuario")
