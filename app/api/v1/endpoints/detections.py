from datetime import datetime
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api import deps
from app.models.detection import Deteccion
from app.schemas.detection import DeteccionCreate, DeteccionResponse
from app.services.event_rules import evaluate_detection_for_event

router = APIRouter()


@router.post(
    "/ingest",
    response_model=DeteccionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingesta de detecciones por visión/IA",
    description=(
        "Recibe detecciones en tiempo real (humo/personas) generadas por el"
        " módulo de visión, las persiste y evalúa reglas de negocio para"
        " generar eventos."
    ),
)
def ingest_detection(
    detection_in: DeteccionCreate,
    db: Session = Depends(deps.get_db),
):
  # 1. Crear y persistir la entidad Deteccion
  db_detection = Deteccion(
      vuelo_id=detection_in.vuelo_id,
      tipo=detection_in.tipo.upper(),
      nivel_confianza=detection_in.nivel_confianza,
      frame_url=detection_in.frame_url,
      latitud=detection_in.latitud,
      longitud=detection_in.longitud,
      timestamp=detection_in.timestamp or datetime.utcnow(),
  )
  db.add(db_detection)
  db.flush()

  # 2. Pasar el registro al servicio de evaluación de eventos
  evaluate_detection_for_event(db, db_detection)

  # 3. Confirmar la transacción
  db.commit()
  db.refresh(db_detection)

  return db_detection