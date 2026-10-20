from datetime import datetime
from sqlalchemy.orm import Session

from app.models.detection import Deteccion
from app.models.event import Evento

UMBRAL_CONFIANZA = 0.70


def evaluate_detection_for_event(
    db: Session, deteccion: Deteccion
) -> Evento | None:
  """Evalúa si una detección califica como evento de seguridad relevante."""
  if deteccion.nivel_confianza < UMBRAL_CONFIANZA:
    return None

  tipo_normalizado = deteccion.tipo.upper()
  fecha_eval = deteccion.timestamp or datetime.utcnow()
  hora = fecha_eval.hour

  nuevo_evento = None

  # 1. Regla de Humo: Siempre crítico si supera el umbral
  if tipo_normalizado == "HUMO":
    nuevo_evento = Evento(
        tipo="HUMO_DETECTADO",
        nivel_criticidad="CRITICA",
        descripcion=(
            f"Detección de humo con confianza del {deteccion.nivel_confianza * 100:.1f}% "
            f"en coordenadas ({deteccion.latitud}, {deteccion.longitud})."
        ),
        estado="PENDIENTE",
        created_at=fecha_eval,
    )

  # 2. Regla de Persona fuera de horario (21:00 a 06:00 hrs)
  elif tipo_normalizado == "PERSONA":
    es_fuera_de_horario = hora >= 21 or hora < 6

    if es_fuera_de_horario:
      nuevo_evento = Evento(
          tipo="PERSONA_NOCTURNA",
          nivel_criticidad="ALTA",
          descripcion=(
              f"Persona detectada fuera de horario regular ({fecha_eval.strftime('%H:%M:%S')}) "
              f"con confianza del {deteccion.nivel_confianza * 100:.1f}%."
          ),
          estado="PENDIENTE",
          created_at=fecha_eval,
      )

  if nuevo_evento:
    db.add(nuevo_evento)
    db.flush()  # Genera el ID del nuevo evento sin cerrar la transacción

    # Enlazar la detección con el evento generado
    deteccion.evento_id = nuevo_evento.id
    db.add(deteccion)

  return nuevo_evento