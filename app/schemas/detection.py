from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class DeteccionBase(BaseModel):
  vuelo_id: int | None = Field(
      None, description="ID del vuelo en curso si existe"
  )
  tipo: str = Field(..., description="Tipo de detección: 'PERSONA' o 'HUMO'")
  nivel_confianza: float = Field(..., ge=0.0, le=1.0, examples=[0.89])
  frame_url: str | None = Field(
      None, description="URL/path del frame con bounding box"
  )
  latitud: float = Field(..., ge=-90.0, le=90.0, examples=[20.5888])
  longitud: float = Field(..., ge=-180.0, le=180.0, examples=[-100.3899])
  timestamp: datetime | None = None


class DeteccionCreate(DeteccionBase):
  pass


class DeteccionResponse(DeteccionBase):
  id: int
  timestamp: datetime
  evento_id: int | None = None

  model_config = ConfigDict(from_attributes=True)