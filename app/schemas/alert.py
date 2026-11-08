from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.event import EventoDetailResponse

class AlertaBase(BaseModel):
    titulo: str
    mensaje: str
    nivel_criticidad: str
    leida: bool = False
    destinatario_rol: str = "GUARDIA"

class AlertaResponse(AlertaBase):
    id: int
    evento_id: int
    timestamp_envio: datetime
    model_config = ConfigDict(from_attributes=True)

class AlertaDetailResponse(AlertaResponse):
    evento: EventoDetailResponse
    model_config = ConfigDict(from_attributes=True)