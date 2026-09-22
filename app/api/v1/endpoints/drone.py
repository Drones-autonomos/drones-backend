import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.drone_service import drone_service

router = APIRouter()
# Usamos un ThreadPoolExecutor para no bloquear el Event Loop de FastAPI con operaciones síncronas de DroneKit
executor = ThreadPoolExecutor(max_workers=2)


class TakeoffRequest(BaseModel):
    altitude: float = 10.0


class ConnectRequest(BaseModel):
    connection_string: str = "127.0.0.1:14550"


@router.post("/connect")
def connect_drone(request: ConnectRequest):
    success = drone_service.connect(request.connection_string)
    if not success:
        raise HTTPException(status_code=500, detail="Fallo al intentar conectar con el dron")
    return {"message": "Dron conectado exitosamente"}


@router.post("/takeoff")
async def takeoff_drone(request: TakeoffRequest):
    loop = asyncio.get_event_loop()
    # Ejecutamos en un hilo separado dado que arm_and_takeoff tiene loops bloqueantes (time.sleep)
    success = await loop.run_in_executor(executor, drone_service.arm_and_takeoff, request.altitude)
    if not success:
        raise HTTPException(status_code=500, detail="Fallo en la secuencia de despegue")
    return {"message": f"Despegue completado a {request.altitude} metros"}


@router.post("/rtl")
def return_to_launch():
    success = drone_service.return_to_launch()
    if not success:
        raise HTTPException(status_code=500, detail="Fallo al ejecutar Return to Launch (RTL)")
    return {"message": "Regresando a base"}
