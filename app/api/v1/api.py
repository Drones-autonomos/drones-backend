from fastapi import APIRouter
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.detections import router as detections_router
from app.api.v1.endpoints.event import router as events_router
from app.api.v1.endpoints.missions import router as missions_router
from app.api.v1.endpoints import auth, missions, drone, detections, event

from app.api.v1.endpoints import auth, drone, missions

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
api_router.include_router(drone.router, prefix="/drone", tags=["Control de Vuelo"])
api_router.include_router(detections.router, prefix="/detections", tags=["Detecciones"])
api_router.include_router(event.router, prefix="/events", tags=["Eventos"])
    return {
        "version": "v1",
        "description": "API REST - Drones Autónomos 67",
        "endpoints_disponibles": [
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            "/api/v1/auth/me",
            "/api/v1/missions/",
            "/api/v1/drone/",
        ],
    }


api_router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
api_router.include_router(missions.router, prefix="/missions", tags=["Misiones"])
api_router.include_router(drone.router, prefix="/drone", tags=["Control de Vuelo"])
