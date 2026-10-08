from fastapi import APIRouter

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
        ],
    }


api_router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
api_router.include_router(missions.router, prefix="/missions", tags=["Misiones"])
api_router.include_router(drone.router, prefix="/drone", tags=["Control de Vuelo"])
