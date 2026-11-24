import asyncio
import logging
import math
import threading
import time
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
from app.services.charging_base_service import charging_base_service
from app.services.drone_service import drone_service
from app.services.mission_service import MissionError, MissionService, get_mission_service
from app.services.notfication_service import notification_manager

router = APIRouter()
# Usamos un ThreadPoolExecutor para no bloquear el Event Loop de FastAPI con operaciones síncronas de DroneKit
executor = ThreadPoolExecutor(max_workers=2)
logger = logging.getLogger(__name__)

ESTADO_CONEXION_DRON = {
    "estado": "OFFLINE",
    "ultima_actualizacion": datetime.utcnow().isoformat(),
    "bateria_porcentaje": None,
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
    _admin: Usuario = Depends(deps.require_admin),
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
            vuelo_id=vuelo_valido_id,
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
def get_connection_status(_user: Usuario = Depends(deps.require_guard_or_admin)):
    vehicle = drone_service.vehicle
    if vehicle is None:
        ESTADO_CONEXION_DRON["estado"] = "OFFLINE"
        ESTADO_CONEXION_DRON["bateria_porcentaje"] = None
    else:
        heartbeat = getattr(vehicle, "last_heartbeat", None)
        ESTADO_CONEXION_DRON["estado"] = (
            "ONLINE"
            if heartbeat is not None and math.isfinite(heartbeat) and heartbeat <= 5
            else "WEAK_SIGNAL"
        )
        ESTADO_CONEXION_DRON["bateria_porcentaje"] = getattr(
            getattr(vehicle, "battery", None), "level", None
        )
    ESTADO_CONEXION_DRON["ultima_actualizacion"] = datetime.utcnow().isoformat()
    return ESTADO_CONEXION_DRON

@router.post("/connect")
def connect_drone(
    request: ConnectRequest,
    service: MissionService = Depends(get_mission_service),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    with service.manual_control(allow_reserved=True):
        success = flight_call(drone_service.connect, request.connection_string)
    if not success:
        raise HTTPException(status_code=500, detail="Fallo al intentar conectar con el dron")
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="CONECTAR_DRON",
        recurso="/api/v1/drone/connect",
        detalle=f"Conexión MAVLink establecida por {current_user.email} hacia {request.connection_string}",
    )
    return {"message": "Dron conectado exitosamente"}


@router.post("/takeoff")
async def takeoff_drone(
    request: TakeoffRequest,
    service: MissionService = Depends(get_mission_service),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    loop = asyncio.get_event_loop()
    # Ejecutamos en un hilo separado dado que arm_and_takeoff tiene loops bloqueantes (time.sleep)
    success = await loop.run_in_executor(executor, takeoff_with_reservation, service, request.altitude)
    if not success:
        raise HTTPException(status_code=500, detail="Fallo en la secuencia de despegue")
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="DESPEGUE_MANUAL",
        recurso="/api/v1/drone/takeoff",
        detalle=f"Despegue manual a {request.altitude} m solicitado por {current_user.email}",
    )
    return {"message": f"Despegue completado a {request.altitude} metros"}


@router.post("/disconnect")
def disconnect_drone(
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    drone_service.close()
    ESTADO_CONEXION_DRON["estado"] = "OFFLINE"
    ESTADO_CONEXION_DRON["bateria_porcentaje"] = None
    ESTADO_CONEXION_DRON["ultima_actualizacion"] = datetime.utcnow().isoformat()
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="DESCONECTAR_DRON",
        recurso="/api/v1/drone/disconnect",
        detalle=f"Conexión MAVLink cerrada por {current_user.email}",
    )
    return {"message": "Dron desconectado"}


@router.post("/pause")
async def pause_flight(
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, flight_call, drone_service.pause_flight)
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="PAUSAR_VUELO",
        recurso="/api/v1/drone/pause",
        detalle=f"Vuelo pausado por {current_user.email} (modo {result.get('modo')})",
    )
    await notification_manager.broadcast_alert(
        {
            "tipo": "VUELO_PAUSADO",
            "severidad": "MEDIA",
            "mensaje": f"Vuelo pausado por {current_user.email} (modo {result['modo']}).",
            "timestamp": datetime.utcnow().isoformat(),
        }
    )
    return result


@router.post("/resume")
async def resume_flight(
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, flight_call, drone_service.resume_flight)
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="REANUDAR_VUELO",
        recurso="/api/v1/drone/resume",
        detalle=f"Vuelo reanudado por {current_user.email}",
    )
    await notification_manager.broadcast_alert(
        {
            "tipo": "VUELO_REANUDADO",
            "severidad": "BAJA",
            "mensaje": f"Vuelo reanudado por {current_user.email}.",
            "timestamp": datetime.utcnow().isoformat(),
        }
    )
    return result


@router.post("/emergency-stop")
async def emergency_stop(
    service: MissionService = Depends(get_mission_service),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    loop = asyncio.get_event_loop()
    active_vuelo_id = service.active_id
    result = await loop.run_in_executor(executor, flight_call, _emergency_land, service)
    threading.Thread(
        target=_reassert_land_until_released,
        args=(service,),
        daemon=True,
        name="emergency-land-reassert",
    ).start()

    ahora = datetime.utcnow()
    registro = BitacoraVuelo(
        vuelo_id=active_vuelo_id,
        operador_id=current_user.id,
        fecha_inicio=ahora,
        fecha_fin=ahora,
        duracion_segundos=0,
        estado_final="PARADA_EMERGENCIA",
        incidentes=f"Parada de emergencia (LAND) ordenada por {current_user.email}.",
    )
    db.add(registro)
    db.commit()
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="PARADA_EMERGENCIA_LAND",
        recurso="/api/v1/drone/emergency-stop",
        detalle=(
            f"LAND inmediato ordenado por {current_user.email}"
            + (f"; misión activa cancelada: {active_vuelo_id}" if active_vuelo_id else "")
        ),
    )
    await notification_manager.broadcast_alert(
        {
            "tipo": "PARADA_EMERGENCIA",
            "severidad": "ALTA",
            "mensaje": f"Parada de emergencia ejecutada por {current_user.email}.",
            "timestamp": ahora.isoformat(),
        }
    )
    return {"detenido": True, "resultado": result}


@router.get("/preflight-check", dependencies=[Depends(deps.require_guard_or_admin)])
def preflight_check():
    return flight_call(drone_service.preflight_check)


@router.get("/failsafe", dependencies=[Depends(deps.require_guard_or_admin)])
def get_failsafe():
    return flight_call(drone_service.get_failsafe_status)


@router.post("/rtl")
def return_to_launch(
    heliport_id: str | None = None,
    service: MissionService = Depends(get_mission_service),
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_guard_or_admin),
):
    coords = None
    if heliport_id:
        coords = flight_call(charging_base_service.station_coords, heliport_id, db=db)

    active_vuelo_id = service.active_id
    if coords is not None and not coords["same_as_home"]:
        resultado = flight_call(_start_pad_return, service, coords)
        destino = coords["station_id"]
    else:
        success = flight_call(service.emergency_rtl, drone_service.return_to_launch)
        if not success:
            raise HTTPException(status_code=500, detail="Fallo al ejecutar Return to Launch (RTL)")
        resultado = {"modo": "RTL"}
        destino = coords["station_id"] if coords else "HOME"

    ahora = datetime.utcnow()
    registro_rtl = BitacoraVuelo(
        vuelo_id=active_vuelo_id,
        operador_id=current_user.id,
        fecha_inicio=ahora,
        fecha_fin=ahora,
        duracion_segundos=0,
        estado_final="RTL_MANUAL",
        incidentes=f"Retorno automático hacia {destino} solicitado manualmente por {current_user.email}.",
    )
    db.add(registro_rtl)
    db.commit()
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="RTL_MANUAL",
        recurso="/api/v1/drone/rtl",
        detalle=(
            f"Retorno solicitado por {current_user.email} hacia {destino}"
            + (f"; misión activa cancelada: {active_vuelo_id}" if active_vuelo_id else "")
        ),
    )

    return {"message": f"Retorno solicitado hacia {destino}", "resultado": resultado}


@router.post("/failsafe")
def configure_failsafe(
    enabled: bool = True,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    result = flight_call(drone_service.configure_gcs_failsafe, enabled=enabled)
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="CONFIGURAR_FAILSAFE_GCS",
        recurso="/api/v1/drone/failsafe",
        detalle=f"FS_GCS_ENABLE={'ON' if enabled else 'OFF'} configurado por {current_user.email}",
    )
    return result


@router.get("/charging-bases", dependencies=[Depends(deps.require_guard_or_admin)])
def list_charging_bases(db: Session = Depends(deps.get_db)):
    return charging_base_service.list_stations(db=db)


@router.get("/charging-base", dependencies=[Depends(deps.require_guard_or_admin)])
def get_charging_base_status(
    station_id: str | None = None,
    db: Session = Depends(deps.get_db),
):
    return flight_call(charging_base_service.get_status, station_id=station_id, db=db)


@router.post("/charging-base/dock-recharge")
def dock_and_recharge(
    target_pct: float = 100.0,
    station_id: str | None = None,
    db: Session = Depends(deps.get_db),
    current_user: Usuario = Depends(deps.require_admin),
):
    result = flight_call(
        charging_base_service.dock_and_recharge,
        drone_service,
        station_id=station_id,
        target_pct=target_pct,
        db=db,
    )
    deps.log_audit_event(
        db,
        usuario_id=current_user.id,
        accion="DOCK_RECARGA",
        recurso="/api/v1/drone/charging-base/dock-recharge",
        detalle=(
            f"Recarga hasta {target_pct}% solicitada por {current_user.email}"
            + (f" en {station_id}" if station_id else "")
        ),
    )
    return result


def _cancel_active_mission(service) -> int | None:
    """Cancela una misión activa para liberar el ejecutor antes de control manual."""
    active_id = service.active_id
    if active_id is None:
        return None
    try:
        service.cancel(active_id)
    except MissionError:
        # La misión pudo terminar entre la lectura y la cancelación.
        logger.info("La misión %s ya no estaba activa al solicitar control manual", active_id)
    return active_id


def _emergency_land(service) -> dict:
    """Cancela la misión activa y asegura LAND inmediato (nunca RTL)."""
    _cancel_active_mission(service)
    last_exc = None
    for _ in range(3):
        try:
            return drone_service.emergency_stop()
        except TimeoutError as exc:
            last_exc = exc
    raise last_exc


def _reassert_land_until_released(service) -> None:
    """Reafirma LAND mientras el ejecutor de misión pueda reenviar RTL residual."""
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline and service.active_id is not None:
        vehicle = drone_service.vehicle
        if vehicle is None:
            return
        try:
            if drone_service.is_grounded():
                return
        except RuntimeError:
            return
        if getattr(getattr(vehicle, "mode", None), "name", None) != "LAND":
            try:
                drone_service._set_mode("LAND")
            except Exception:
                logger.debug("No se pudo reafirmar LAND durante la parada de emergencia", exc_info=True)
        time.sleep(0.5)


def _start_pad_return(service, coords: dict) -> dict:
    """Precheck síncrono y navegación al pad en un hilo daemon."""
    _cancel_active_mission(service)
    drone_service.ensure_connected()
    if not drone_service.vehicle.armed:
        raise RuntimeError("No hay un vuelo activo para redirigir al helipuerto")
    threading.Thread(
        target=_pad_return_worker,
        args=(coords,),
        daemon=True,
        name=f"rtl-{coords['station_id']}",
    ).start()
    return {"modo": "GUIDED_PAD", "destino": coords["station_id"]}


def _pad_return_worker(coords: dict) -> None:
    try:
        # Breve margen para que el ejecutor de misión entre a su cierre y luego
        # el retorno al pad tome el control del vehículo.
        time.sleep(1.0)
        drone_service.return_to_heliport(coords["lat"], coords["lon"])
    except Exception:
        logger.exception("Falló el retorno al helipuerto %s", coords["station_id"])


def takeoff_with_reservation(service, altitude):
    # La reserva pertenece al hilo: desconectar el cliente HTTP no libera un vuelo aún activo.
    with service.manual_control():
        return flight_call(drone_service.arm_and_takeoff, altitude)


def flight_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except MissionError:
        raise
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
