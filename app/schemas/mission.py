from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WaypointBase(BaseModel):
  orden_waypoint: int = Field(..., ge=1, examples=[1])
  latitud: float = Field(..., ge=-90.0, le=90.0, examples=[20.5888])
  longitud: float = Field(..., ge=-180.0, le=180.0, examples=[-100.3899])
  altitud_metros: float = Field(default=15.0, ge=2.0, le=200.0, examples=[15.0])


class WaypointResponse(WaypointBase):
  id: int
  model_config = ConfigDict(from_attributes=True)


class MisionBase(BaseModel):
  nombre: str = Field(..., min_length=3, max_length=100)
  descripcion: str | None = None
  horario_inicio_programado: datetime | None = None


class MisionCreate(MisionBase):
  waypoints: list[WaypointBase] = Field(..., min_length=2)


class MisionUpdate(BaseModel):
  nombre: str | None = None
  descripcion: str | None = None
  horario_inicio_programado: datetime | None = None


class MisionResponse(MisionBase):
  id: int
  creado_por: int
  estado: str
  created_at: datetime
  waypoints: list[WaypointResponse] = []

  model_config = ConfigDict(from_attributes=True)
