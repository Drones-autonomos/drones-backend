from datetime import datetime, timedelta
from sqlalchemy import DateTime, ForeignKey, Integer, BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base

class Grabacion(Base):
    __tablename__ = "grabaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    vuelo_id: Mapped[int | None] = mapped_column(Integer, nullable=True) # ForeignKey a vuelos.id si existe
    ruta_archivo: Mapped[str] = mapped_column(String(500), nullable=False)
    fecha_grabacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    duracion_segundos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fecha_purga: Mapped[datetime] = mapped_column(
        DateTime, 
        default=lambda: datetime.utcnow() + timedelta(days=30), 
        nullable=False
    )