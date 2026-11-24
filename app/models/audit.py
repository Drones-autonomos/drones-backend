import hashlib
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, event, select
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
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    usuario: Mapped["Usuario"] = relationship("Usuario")


def compute_audit_hash(
    prev_hash: str | None,
    usuario_id: int | None,
    accion: str | None,
    recurso: str | None,
    detalle: str | None,
    timestamp: datetime | None,
) -> str:
    """Serialización canónica del registro para la cadena de sellado SHA-256."""
    payload = "|".join(
        [
            prev_hash or "",
            "" if usuario_id is None else str(usuario_id),
            accion or "",
            recurso or "",
            detalle or "",
            timestamp.isoformat() if timestamp else "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _seal_audit_record(mapper, connection, target: Auditoria):
    """Sella cada inserción encadenándola al hash del registro anterior."""
    if target.timestamp is None:
        target.timestamp = datetime.utcnow()
    prev = connection.execute(
        select(Auditoria.hash_sha256).order_by(Auditoria.id.desc()).limit(1)
    ).scalar()
    target.prev_hash = prev
    target.hash_sha256 = compute_audit_hash(
        prev,
        target.usuario_id,
        target.accion,
        target.recurso,
        target.detalle,
        target.timestamp,
    )


def _block_audit_modification(mapper, connection, target):
    raise ValueError("Operación prohibida: registro inmutable (solo inserción).")


event.listen(Auditoria, "before_insert", _seal_audit_record)
event.listen(Auditoria, "before_update", _block_audit_modification)
event.listen(Auditoria, "before_delete", _block_audit_modification)
