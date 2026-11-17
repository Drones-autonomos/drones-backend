from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base
from app.models.user import Usuario

class Auditoria(Base):
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)
    accion: Mapped[str] = mapped_column(String(50), nullable=False)        # Ej. CREAR_MISION, CONSULTAR_GRABACION
    recurso: Mapped[str] = mapped_column(String(100), nullable=False)      # Ej. /api/v1/missions/12
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_origen: Mapped[str | None] = mapped_column(String(45), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    usuario: Mapped["Usuario"] = relationship("Usuario")


def _block_audit_modification(mapper, connection, target):
    raise ValueError("Operación prohibida: registro inmutable (solo inserción).")

event.listen(Auditoria, "before_update", _block_audit_modification)
event.listen(Auditoria, "before_delete", _block_audit_modification)