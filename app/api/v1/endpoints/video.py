"""Endpoints de streaming de video en vivo y telemetría sincronizada."""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.api import deps
from app.services.drone_service import drone_service
from app.services.video_stream_service import video_stream_service

router = APIRouter()


class StreamInfoResponse(BaseModel):
    stream_url: str
    protocolo: str
    estado_camara: str
    resolucion: str
    fps: int
    frames_publicados: int = 0
    reconexiones: int = 0
    ultimo_frame_at: str | None = None


@router.get(
    "/stream-info",
    response_model=StreamInfoResponse,
    summary="Información del stream de video en vivo",
    description=(
        "Retorna la URL del servidor de streaming configurado para el dron "
        "(MJPEG/WebSocket/RTSP), su estado y métricas de transmisión."
    ),
)
def get_stream_info():
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
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Frame vacío")
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
def get_snapshot():
    frame = video_stream_service.get_latest()
    if frame is None:
        raise HTTPException(status_code=404, detail="No hay frames disponibles en el stream")
    return Response(content=frame.jpeg_bytes, media_type="image/jpeg")


@router.get(
    "/live",
    summary="Stream de video en vivo (MJPEG)",
)
def live_mjpeg_stream(max_frames: int | None = Query(None, ge=1, le=1000)):
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
    vehicle = getattr(drone_service, "vehicle", None)
    if vehicle is None:
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "connected": False,
            "stream": status_info,
        }
    loc = getattr(vehicle.location, "global_relative_frame", None)
    battery = getattr(vehicle, "battery", None)
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "connected": True,
        "armed": bool(getattr(vehicle, "armed", False)),
        "mode": getattr(getattr(vehicle, "mode", None), "name", None),
        "latitud": getattr(loc, "lat", None),
        "longitud": getattr(loc, "lon", None),
        "altitud_m": getattr(loc, "alt", None),
        "bateria_pct": getattr(battery, "level", None),
        "stream": status_info,
    }


@router.websocket("/ws/telemetry")
async def websocket_video_telemetry(websocket: WebSocket):
    """Canal WebSocket para telemetría sincronizada con el stream en vivo."""
    await video_telemetry_manager.connect(websocket)
    try:
        while True:
            data = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            if data == "ping":
                await websocket.send_text("pong")
            elif data == "status":
                await websocket.send_json(_snapshot_telemetry())
    except TimeoutError:
        await websocket.send_json(_snapshot_telemetry())
    except WebSocketDisconnect:
        video_telemetry_manager.disconnect(websocket)
