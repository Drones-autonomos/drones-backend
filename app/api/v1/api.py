from fastapi import APIRouter

from app.api.v1.endpoints import auth, drone

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
api_router.include_router(drone.router, prefix="/drone", tags=["Control de Vuelo"])
