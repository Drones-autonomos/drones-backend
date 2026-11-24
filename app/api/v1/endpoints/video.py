"""Endpoints de streaming de video en vivo, captura sellada de evidencia y telemetría sincronizada."""

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.models.audit import Auditoria
from app.models.detection import Deteccion
from app.models.setting import AjustesOperativos
from app.models.user import Usuario
from app.services.drone_service import drone_service
from app.services.video_stream_service import video_stream_service
from app.vision.pipeline import FramePipeline

router = APIRouter()
EVIDENCE_FRAMES_DIR = Path(os.getenv("STORAGE_FRAMES_PATH", "storage/frames"))
EVIDENCE_FRAMES_DIR.mkdir(parents=True, exist_ok=True)


class StreamInfoResponse(BaseModel):
    stream_url: str
    protocolo: str
    estado_camara: str
    resolucion: str
    fps: int
    calidad_perfil: str = "fhd-60"
    frames_publicados: int = 0
    reconexiones: int = 0
    ultimo_frame_at: str | None = None


class CaptureEvidenceResponse(BaseModel):
    id: int
    frame_url: str
    download_url: str
    checksum_sha256: str
    latitud: float
    longitud: float
    altitud_metros: float | None = None
    timestamp: str


def _extract_token(request: Request, query_token: str | None) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    if query_token:
        return query_token.strip()
    return None


def _validate_jwt_user(db: Session, raw_token: str) -> Usuario:
    try:
        user = deps.get_current_user_ws_or_query(db, raw_token)
    except HTTPException as exc:
        if exc.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.detail) from exc
        raise
    if not user.rol or user.rol.nombre not in ("ADMIN", "GUARDIA"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol no autorizado para video")
    return user


def _authorize_video_access(
    request: Request,
    token: str | None,
    db: Session,
    *,
    require_strict: bool = False,
) -> Usuario | None:
    raw_token = _extract_token(request, token)
    if raw_token:
        return _validate_jwt_user(db, raw_token)
    strict_env = os.getenv("VIDEO_REQUIRE_AUTH", "false").lower() == "true"
    if require_strict or strict_env:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere autenticación Bearer o parámetro token para acceder al stream de video",
        )
    return None


def _sync_quality_from_db(db: Session) -> None:
    try:
        row = db.query(AjustesOperativos).order_by(AjustesOperativos.id.asc()).first()
        if row and row.transmission_quality_id:
            video_stream_service.apply_quality_profile(row.transmission_quality_id)
    except Exception:
        pass


@router.get(
    "/stream-info",
    response_model=StreamInfoResponse,
    summary="Información del stream de video en vivo",
    description=(
        "Retorna la URL del servidor de streaming configurado para el dron "
        "(MJPEG/WebSocket/RTSP), su estado y métricas de transmisión."
    ),
)
def get_stream_info(
    request: Request,
    token: str | None = Query(None),
    db: Session = Depends(deps.get_db),
):
    _authorize_video_access(request, token, db, require_strict=False)
    _sync_quality_from_db(db)
    return StreamInfoResponse(**video_stream_service.get_status())


@router.post(
    "/frame",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(deps.require_admin)],
    summary="Publicar frame de cámara al stream en vivo",
)
async def push_video_frame(
    file: UploadFile = File(...),
    width: int = Query(1280, ge=16, le=7680),
    height: int = Query(720, ge=16, le=4320),
    blur_faces: bool = Query(False, description="Difuminar rostros detectados antes de publicar"),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Frame vacío")
    if blur_faces:
        arr = np.frombuffer(content, dtype=np.uint8)
        decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if decoded is not None:
            anonymized = FramePipeline.blur_faces(decoded)
            ok, encoded = cv2.imencode(".jpg", anonymized)
            if ok:
                content = encoded.tobytes()
    frame = video_stream_service.publish_jpeg(content, width=width, height=height)
    return {
        "sequence": frame.sequence,
        "timestamp": frame.timestamp.isoformat(),
        "bytes": len(frame.jpeg_bytes),
    }


@router.get(
    "/snapshot",
    summary="Obtener último frame JPEG del stream",
)
def get_snapshot(
    request: Request,
    token: str | None = Query(None),
    blur_faces: bool = Query(False, description="Aplicar difuminado facial de privacidad"),
    db: Session = Depends(deps.get_db),
):
    _authorize_video_access(request, token, db, require_strict=False)
    frame = video_stream_service.get_latest()
    if frame is None:
        raise HTTPException(status_code=404, detail="No hay frames disponibles en el stream")

    payload = frame.jpeg_bytes
    if blur_faces:
        arr = np.frombuffer(payload, dtype=np.uint8)
        decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if decoded is not None:
            anonymized = FramePipeline.blur_faces(decoded)
            ok, encoded = cv2.imencode(".jpg", anonymized)
            if ok:
                payload = encoded.tobytes()

    return Response(content=payload, media_type="image/jpeg")


@router.post(
    "/capture-evidence",
    response_model=CaptureEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Capturar y sellar evidencia visual desde el stream en vivo",
)
def capture_live_evidence(
    request: Request,
    token: str | None = Query(None),
    vuelo_id: int | None = Query(None),
    blur_faces: bool = Query(True, description="Aplicar anonimización facial reglamentaria"),
    db: Session = Depends(deps.get_db),
):
    user = _authorize_video_access(request, token, db, require_strict=True)
    frame = video_stream_service.get_latest()
    if frame is None:
        raise HTTPException(status_code=404, detail="No hay transmisión activa para capturar evidencia")

    jpeg_bytes = frame.jpeg_bytes
    if blur_faces:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if decoded is not None:
            anonymized = FramePipeline.blur_faces(decoded)
            ok, encoded = cv2.imencode(".jpg", anonymized)
            if ok:
                jpeg_bytes = encoded.tobytes()

    now = datetime.now(UTC).replace(tzinfo=None)
    stamp = now.strftime("%Y%m%d_%H%M%S_%f")
    EVIDENCE_FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"evidencia_{stamp}.jpg"
    file_path = EVIDENCE_FRAMES_DIR / filename
    file_path.write_bytes(jpeg_bytes)
    checksum = hashlib.sha256(jpeg_bytes).hexdigest()

    lat, lon, alt = 20.70428, -100.44358, None
    vehicle = getattr(drone_service, "vehicle", None)
    if vehicle is not None:
        loc = getattr(getattr(vehicle, "location", None), "global_relative_frame", None)
        if loc is not None:
            if getattr(loc, "lat", None) is not None:
                lat = float(loc.lat)
            if getattr(loc, "lon", None) is not None:
                lon = float(loc.lon)
            if getattr(loc, "alt", None) is not None:
                alt = float(loc.alt)

    deteccion = Deteccion(
        vuelo_id=vuelo_id,
        tipo="EVIDENCIA_MANUAL",
        nivel_confianza=1.0,
        frame_url=str(file_path),
        latitud=lat,
        longitud=lon,
        altitud_metros=alt,
        checksum_sha256=checksum,
        timestamp=now,
    )
    db.add(deteccion)
    db.flush()

    db.add(
        Auditoria(
            usuario_id=user.id if user else None,
            accion="CAPTURAR_EVIDENCIA_VIDEO",
            recurso=f"/api/v1/detections/{deteccion.id}/frame",
            detalle=f"Captura sellada SHA-256={checksum[:12]}... en ({lat:.5f}, {lon:.5f})",
            ip_origen=request.client.host if request.client else "unknown",
        )
    )
    db.commit()
    db.refresh(deteccion)

    download_url = f"/api/v1/detections/{deteccion.id}/frame"
    return CaptureEvidenceResponse(
        id=deteccion.id,
        frame_url=str(file_path),
        download_url=download_url,
        checksum_sha256=checksum,
        latitud=float(deteccion.latitud),
        longitud=float(deteccion.longitud),
        altitud_metros=deteccion.altitud_metros,
        timestamp=now.isoformat(),
    )


@router.get(
    "/live",
    summary="Stream de video en vivo (MJPEG)",
)
def live_mjpeg_stream(
    request: Request,
    max_frames: int | None = Query(None, ge=1, le=1000),
    token: str | None = Query(None),
    db: Session = Depends(deps.get_db),
):
    _authorize_video_access(request, token, db, require_strict=False)
    _sync_quality_from_db(db)
    if video_stream_service.get_latest() is None:
        raise HTTPException(status_code=404, detail="Stream sin señal activa")
    return StreamingResponse(
        video_stream_service.iter_mjpeg(max_frames=max_frames),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


class VideoTelemetryManager:
    """Administra las conexiones que reciben telemetría sincronizada con el stream."""

    def __init__(self):
        self.active_subscribers: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_subscribers.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_subscribers:
            self.active_subscribers.remove(websocket)

    async def broadcast_telemetry(self, telemetry_data: dict):
        disconnected = []
        for connection in self.active_subscribers:
            try:
                await connection.send_json(telemetry_data)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)


video_telemetry_manager = VideoTelemetryManager()


def _snapshot_telemetry() -> dict:
    status_info = video_stream_service.get_status()
    paused = bool(getattr(drone_service, "paused", False))
    vehicle = getattr(drone_service, "vehicle", None)
    if vehicle is None:
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "connected": False,
            "pausado": False,
            "stream": status_info,
        }
    loc = getattr(vehicle.location, "global_relative_frame", None)
    battery = getattr(vehicle, "battery", None)
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "connected": True,
        "armed": bool(getattr(vehicle, "armed", False)),
        "pausado": paused,
        "mode": getattr(getattr(vehicle, "mode", None), "name", None),
        "latitud": getattr(loc, "lat", None),
        "longitud": getattr(loc, "lon", None),
        "altitud_m": getattr(loc, "alt", None),
        "bateria_pct": getattr(battery, "level", None),
        "stream": status_info,
    }


@router.websocket("/ws/telemetry")
async def websocket_video_telemetry(
    websocket: WebSocket,
    token: str | None = Query(None),
    db: Session = Depends(deps.get_db),
):
    """Canal WebSocket para telemetría sincronizada con el stream en vivo."""
    strict_env = os.getenv("VIDEO_REQUIRE_AUTH", "false").lower() == "true"
    if token or strict_env:
        if not token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        try:
            user = deps.get_current_user_ws_or_query(db, token)
            if not user.rol or user.rol.nombre not in ("ADMIN", "GUARDIA"):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        except HTTPException:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await video_telemetry_manager.connect(websocket)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            except TimeoutError:
                await websocket.send_json(_snapshot_telemetry())
                continue
            if data == "ping":
                await websocket.send_text("pong")
            elif data == "status":
                await websocket.send_json(_snapshot_telemetry())
    except WebSocketDisconnect:
        pass
    finally:
        video_telemetry_manager.disconnect(websocket)
