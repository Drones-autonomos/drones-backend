import json
from fastapi import WebSocket

class NotificationManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_alert(self, alert_data: dict):
        """Envía la alerta a todos los guardias conectados en tiempo real."""
        disconnected = []
        message = json.dumps(alert_data)
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)

        for dead in disconnected:
            self.disconnect(dead)

notification_manager = NotificationManager()