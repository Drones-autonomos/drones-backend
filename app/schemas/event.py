from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.detection import DeteccionResponse


class EventoBase(BaseModel):
    tipo: str = Field(
        ...,
        description="Tipo de evento: 'PERSONA_NOCTURNA', 'PERSONA_ZONA_RESTRINGIDA' o 'HUMO_DETECTADO'",
    )
    nivel_criticidad: str = Field(..., description="Criticidad: 'BAJA', 'MEDIA', 'ALTA' o 'CRITICA'")
    descripcion: str | None = None
    estado: str = Field(default="PENDIENTE", description="Estado: 'PENDIENTE', 'EN_REVISION' o 'RESUELTO'")


class EventoStatusUpdate(BaseModel):
    estado: str = Field(
        ...,
        pattern="^(EN_REVISION|RESUELTO)$",
        description="Nuevo estado del evento. Valores permitidos: 'EN_REVISION' o 'RESUELTO'",
        examples=["EN_REVISION"],
    )
    notas_resolucion: str | None = Field(
        None,
        max_length=1000,
        description="Notas operativas de despacho o cierre del incidente",
    )


class EventoResponse(EventoBase):
    id: int
    created_at: datetime
    atendido_por_id: int | None = None
    resuelto_por_id: int | None = None
    despachado_at: datetime | None = None
    resuelto_at: datetime | None = None
    notas_resolucion: str | None = None

    model_config = ConfigDict(from_attributes=True)


class EventoDetailResponse(EventoResponse):
    detecciones: list[DeteccionResponse] = []

    model_config = ConfigDict(from_attributes=True)
