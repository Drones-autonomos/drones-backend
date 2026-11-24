import hashlib
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.models.detection import Deteccion
from app.models.user import Usuario
from app.schemas.detection import DeteccionCreate, DeteccionResponse
from app.services.event_rules import evaluate_detection_for_event

router = APIRouter()
BACKEND_ROOT = Path(__file__).resolve().parents[4]


def _validate_ingestion_auth(request: Request, db: Session) -> None:
    expected_key = os.getenv("INGESTION_API_KEY", "").strip()
    sent_key = request.headers.get("X-Ingestion-Key", "").strip()
    auth_header = request.headers.get("Authorization", "").strip()

    if sent_key:
        if expected_key and sent_key != expected_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Ingestion-Key inválida")
        return

    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id = payload.get("sub")
            user = db.query(Usuario).filter(Usuario.id == int(user_id)).first() if user_id else None
        except (JWTError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de ingesta inválido") from exc
        if not user or not user.activo or not user.rol or user.rol.nombre not in ("ADMIN", "GUARDIA"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol no autorizado para ingesta")
        return

    if expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere X-Ingestion-Key o Bearer token para ingestar detecciones",
        )


def _authorize_frame_viewer(request: Request, token: str | None, db: Session) -> Usuario:
    auth_header = request.headers.get("Authorization", "")
    raw_token = (
        auth_header.split(" ", 1)[1].strip()
        if auth_header.lower().startswith("bearer ")
        else (token or "").strip()
    )
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticación requerida")
    try:
        user = deps.get_current_user_ws_or_query(db, raw_token)
    except HTTPException as exc:
        if exc.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.detail) from exc
        raise
    if not user.rol or user.rol.nombre not in ("ADMIN", "GUARDIA"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operación no permitida")
    return user


def _resolve_evidence_file(frame_url: str | None) -> Path | None:
    if not frame_url:
        return None
    cleaned = frame_url.strip()
    if ".." in Path(cleaned).parts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ruta de evidencia no permitida")

    candidates = [
        Path(cleaned),
        Path(cleaned.lstrip("/")),
        BACKEND_ROOT / cleaned.lstrip("/"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@router.post(
    "/ingest",
    response_model=DeteccionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingesta de detecciones por visión/IA",
    description=(
        "Recibe detecciones en tiempo real (humo/personas) generadas por el "
        "módulo de visión, las persiste y evalúa reglas de negocio para "
        "generar eventos."
    ),
)
async def ingest_detection(
    detection_in: DeteccionCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
):
    _validate_ingestion_auth(request, db)

    checksum = detection_in.checksum_sha256
    if not checksum and detection_in.frame_url:
        resolved = _resolve_evidence_file(detection_in.frame_url)
        if resolved is not None:
            checksum = hashlib.sha256(resolved.read_bytes()).hexdigest()

    db_detection = Deteccion(
        vuelo_id=detection_in.vuelo_id,
        tipo=detection_in.tipo.upper(),
        nivel_confianza=detection_in.nivel_confianza,
        frame_url=detection_in.frame_url,
        latitud=detection_in.latitud,
        longitud=detection_in.longitud,
        altitud_metros=detection_in.altitud_metros,
        checksum_sha256=checksum,
        timestamp=detection_in.timestamp or datetime.utcnow(),
    )
    db.add(db_detection)
    db.flush()

    await evaluate_detection_for_event(db, db_detection)

    db.commit()
    db.refresh(db_detection)
    return db_detection


@router.get(
    "/{id}/frame",
    summary="Obtener imagen JPEG de evidencia de una detección",
    description="Sirve el fotograma anotado de una detección autenticando vía Bearer o parámetro token.",
)
def get_detection_evidence_frame(
    id: int,
    request: Request,
    token: str | None = Query(None),
    db: Session = Depends(deps.get_db),
):
    _authorize_frame_viewer(request, token, db)
    det = db.query(Deteccion).filter(Deteccion.id == id).first()
    if not det:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detección no encontrada")

    file_path = _resolve_evidence_file(det.frame_url)
    if file_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo de evidencia visual no disponible en el servidor",
        )

    content = file_path.read_bytes()
    checksum = det.checksum_sha256 or hashlib.sha256(content).hexdigest()
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={
            "X-Evidence-SHA256": checksum,
            "Cache-Control": "private, max-age=300",
        },
    )
