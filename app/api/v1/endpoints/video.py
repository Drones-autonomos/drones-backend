import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

router = APIRouter()


class StreamInfoResponse(BaseModel):
    stream_url: str
    protocolo: str
    estado_camara: str
    resolucion: str
    fps: int


@router.get(
    "/stream-info",
    response_model=StreamInfoResponse,
    summary="Información del stream de video en vivo",
    description="Retorna la URL del servidor de streaming configurado para el dron (WebRTC/RTSP), su estado y resolución.",
)
def get_stream_info():
    return StreamInfoResponse(
        stream_url="ws://localhost:8554/live/drone-camera",
        protocolo="WebRTC",
        estado_camara="ONLINE",
        resolucion="1920x1080",
        fps=30,
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


@router.websocket("/ws/telemetry")
async def websocket_video_telemetry(websocket: WebSocket):
    """
    Canal WebSocket para transmitir datos en vivo del dron sincronizados con el video:
    batería, altitud, coordenadas actuales y estado de grabación.
    """
    await video_telemetry_manager.connect(websocket)
    try:
        while True:
            # En un entorno real se lee de app.services.drone_service
            # Aquí se mantiene la escucha o se envían pings periódicos
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        video_telemetry_manager.disconnect(websocket)