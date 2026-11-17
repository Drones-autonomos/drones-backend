import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.flight_log import BitacoraVuelo
from app.models.mission import Mision
from app.models.user import Usuario
from app.schemas.geofence import DroneConnectionEventCreate
from app.services.drone_service import drone_service
from app.services.mission_service import MissionError, MissionService, get_mission_service
from app.services.notfication_service import notification_manager

router = APIRouter()
# Usamos un ThreadPoolExecutor para no bloquear el Event Loop de FastAPI con operaciones síncronas de DroneKit
executor = ThreadPoolExecutor(max_workers=2)

ESTADO_CONEXION_DRON = {
    "estado": "ONLINE",
    "ultima_actualizacion": datetime.utcnow().isoformat(),
    "bateria_porcentaje": 100.0,
}


class TakeoffRequest(BaseModel):
    altitude: float = Field(default=10.0, ge=2.0, le=200.0, allow_inf_nan=False)


class ConnectRequest(BaseModel):
    connection_string: str = "127.0.0.1:14550"

@router.post(
    "/connection-event",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar evento de enlace y RTL del dron",
    description=(
        "Recibe cambios de conectividad (ONLINE, WEAK_SIGNAL, DISCONNECTED_RTL) desde SITL/MAVProxy. "
        "Si se activa RTL, inserta un registro inmutable en la bitácora de vuelos."
    ),
)
async def register_connection_event(
    evento: DroneConnectionEventCreate,
    db: Session = Depends(deps.get_db),
):
    ahora = datetime.utcnow()

    # 1. Actualizar estado actual para consulta del indicador en el dashboard
    ESTADO_CONEXION_DRON["estado"] = evento.estado_enlace
    ESTADO_CONEXION_DRON["ultima_actualizacion"] = ahora.isoformat()
    if evento.bateria_porcentaje is not None:
        ESTADO_CONEXION_DRON["bateria_porcentaje"] = evento.bateria_porcentaje

    bitacora_registrada = False

    # 2. Si se activa el Retorno Automático (RTL), insertar registro inmutable en bitacora_vuelos
    if evento.estado_enlace == "DISCONNECTED_RTL":
        vuelo_valido_id = None
        if evento.vuelo_id is not None:
            mision_existe = db.query(Mision).filter(Mision.id == evento.vuelo_id).first()
            if mision_existe:
                vuelo_valido_id = mision_existe.id

        descripcion_incidente = (
            f"Pérdida de enlace detectada. Retorno automático (RTL) activado. "
            f"{evento.detalle or ''}".strip()
        )
        nuevo_registro_bitacora = BitacoraVuelo(
            vuelo_id=evento.vuelo_id,
            operador_id=None,
            fecha_inicio=ahora,
            fecha_fin=ahora,
            duracion_segundos=0,
            estado_final="RTL_ACTIVADO",
            incidentes=descripcion_incidente,
            resumen_telemetria={
                "evento_conectividad": evento.estado_enlace,
                "bateria_porcentaje": evento.bateria_porcentaje,
                "vuelo_id": evento.vuelo_id,
            },
        )
        db.add(nuevo_registro_bitacora)
        db.commit()
        bitacora_registrada = True

        # Notificar en tiempo real al dashboard vía WebSocket
        await notification_manager.broadcast_alert(
            {
                "tipo": "CONECTIVIDAD_RTL",
                "severidad": "ALTA",
                "estado_enlace": evento.estado_enlace,
                "mensaje": descripcion_incidente,
                "timestamp": ahora.isoformat(),
            }
        )

    return {
        "mensaje": f"Estado de enlace '{evento.estado_enlace}' procesado correctamente.",
        "estado_actual": ESTADO_CONEXION_DRON,
        "registrado_en_bitacora": bitacora_registrada,
    }

@router.get(
    "/connection-status",
    summary="Consultar estado actual de enlace del dron",
    description="Endpoint para el indicador del dashboard (en línea, señal débil, desconectado).",
)
def get_connection_status():
    return ESTADO_CONEXION_DRON

@router.post("/connect", dependencies=[Depends(deps.require_admin)])
def connect_drone(request: ConnectRequest, service: MissionService = Depends(get_mission_service)):
    with service.manual_control(allow_reserved=True):
        success = flight_call(drone_service.connect, request.connection_string)
    if not success:
        raise HTTPException(status_code=500, detail="Fallo al intentar conectar con el dron")
    return {"message": "Dron conectado exitosamente"}


@router.post("/takeoff", dependencies=[Depends(deps.require_admin)])
async def takeoff_drone(request: TakeoffRequest, service: MissionService = Depends(get_mission_service)):
    loop = asyncio.get_event_loop()
    # Ejecutamos en un hilo separado dado que arm_and_takeoff tiene loops bloqueantes (time.sleep)
    success = await loop.run_in_executor(executor, takeoff_with_reservation, service, request.altitude)
    if not success:
        raise HTTPException(status_code=500, detail="Fallo en la secuencia de despegue")
    return {"message": f"Despegue completado a {request.altitude} metros"}


@router.post("/rtl", dependencies=[Depends(deps.require_guard_or_admin)])
def return_to_launch(service: MissionService = Depends(get_mission_service), db: Session = Depends(deps.get_db), current_user: Usuario = Depends(deps.require_guard_or_admin)):
    success = flight_call(service.emergency_rtl, drone_service.return_to_launch)
    if not success:
        raise HTTPException(status_code=500, detail="Fallo al ejecutar Return to Launch (RTL)")
    ahora = datetime.utcnow()
    registro_rtl = BitacoraVuelo(
        vuelo_id=None,
        operador_id=current_user.id,
        fecha_inicio=ahora,
        fecha_fin=ahora,
        duracion_segundos=0,
        estado_final="RTL_MANUAL",
        incidentes=f"Retorno automático (RTL) solicitado manualmente por {current_user.email}.",
    )
    db.add(registro_rtl)
    db.commit()

    return {"message": "RTL solicitado; consulta la misión para confirmar el aterrizaje"}


def takeoff_with_reservation(service, altitude):
    # La reserva pertenece al hilo: desconectar el cliente HTTP no libera un vuelo aún activo.
    with service.manual_control():
        return flight_call(drone_service.arm_and_takeoff, altitude)


def flight_call(operation, *args):
    try:
        return operation(*args)
    except MissionError:
        raise
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
