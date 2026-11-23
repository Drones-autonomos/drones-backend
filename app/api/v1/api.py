from fastapi import APIRouter

from app.api.v1.endpoints import (
    alerts,
    auth,
    detections,
    drone,
    event,
    geofence,
    missions,
    recordings,
    settings,
    audit,
    flight_logs, 
    geofences,
    telemetry,
    video,
)

api_router = APIRouter()


@api_router.get("/")
def v1_root():
    return {
        "version": "v1",
        "description": "API REST - Drones Autónomos 67",
        "endpoints_disponibles": [
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/auth/me",
            "/api/v1/missions/",
            "/api/v1/drone/",
            "/api/v1/detections/ingest",
        ],
    }


api_router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
api_router.include_router(missions.router, prefix="/missions", tags=["Misiones"])
api_router.include_router(detections.router, prefix="/detections", tags=["Detecciones"])
api_router.include_router(event.router, prefix="/events", tags=["Eventos"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["Alertas"])
api_router.include_router(video.router, prefix="/video", tags=["Video"])

api_router.include_router(drone.router, prefix="/drone", tags=["Control de Vuelo"])
api_router.include_router(geofence.router, prefix="/geofences", tags=["Geocercas"])
api_router.include_router(telemetry.router, prefix="/telemetry", tags=["Telemetría"])
api_router.include_router(recordings.router, prefix="/recordings", tags=["Grabaciones"])
api_router.include_router(settings.router, prefix="/settings", tags=["Configuración Normativa"])

api_router.include_router(flight_logs.router, prefix="/flight-logs", tags=["Bitácora de Vuelos"])
api_router.include_router(audit.router, prefix="/audit", tags=["Auditoría"])
api_router.include_router(geofences.router, prefix="/geofences", tags=["Geofencing"])
