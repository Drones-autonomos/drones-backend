from datetime import datetime
from pydantic import BaseModel, ConfigDict

class GrabacionBase(BaseModel):
    vuelo_id: int | None = None
    duracion_segundos: int
    tamano_bytes: int
    checksum_sha256: str

class GrabacionResponse(GrabacionBase):
    id: int
    ruta_archivo: str
    fecha_grabacion: datetime
    fecha_purga: datetime
    dias_restantes_purga: int | None = None

    model_config = ConfigDict(from_attributes=True)