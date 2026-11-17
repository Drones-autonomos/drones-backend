from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base
from app.models.user import Usuario

class BitacoraVuelo(Base):
    __tablename__ = "bitacora_vuelos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vuelo_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("misiones.id"), nullable=True)
    operador_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha_inicio: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    fecha_fin: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duracion_segundos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estado_final: Mapped[str] = mapped_column(String(30), default="EN_CURSO", nullable=False)
    incidentes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resumen_telemetria: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    operador: Mapped["Usuario"] = relationship("Usuario")

def _block_flight_log_modification(mapper, connection, target):
    raise ValueError("Operación prohibida: registro inmutable (solo inserción).")

event.listen(BitacoraVuelo, "before_update", _block_flight_log_modification)
event.listen(BitacoraVuelo, "before_delete", _block_flight_log_modification)