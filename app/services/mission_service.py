"""Orquestación de un vehículo. Ejecutar una sola instancia/worker de control."""

import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, RLock, Thread

from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.detection import Deteccion
from app.models.flight_log import BitacoraVuelo
from app.models.mission import Mision, Ruta
from app.models.telemetry import TelemetriaVuelo
from app.schemas.mission import MisionCreate, WaypointBase
from app.services.drone_service import FlightCancelled, drone_service
from app.services.geofence_service import (
    evaluate_route_against_zones,
    validate_waypoints_in_db,
)
from app.services.telemetry_service import log_drone_snapshot

logger = logging.getLogger(__name__)


class MissionError(RuntimeError):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


class MissionService:
    def __init__(self, session_factory=SessionLocal, drone=drone_service, thread_factory=Thread):
        self.sessions = session_factory
        self.drone = drone
        self.thread_factory = thread_factory
        self.lock = RLock()
        self.active_id = None
        self.cancel_event = Event()
        self.worker = None
        self.manual_busy = False
        self.stop_event = Event()
        self.scheduler = None

    @staticmethod
    def _mission(db, mission_id):
        mission = db.query(Mision).filter(Mision.id == mission_id).with_for_update().first()
        if mission is None:
            raise MissionError("Misión no encontrada", 404)
        return mission

    def start(self, mission_id, ejecutado_por=None):
        with self.lock:
            if self.active_id is not None or self.manual_busy:
                raise MissionError("El vehículo ya está ocupado")
            with self.sessions() as db:
                mission = self._mission(db, mission_id)
                if mission.estado != "PROGRAMADA":
                    raise MissionError("Solo se pueden iniciar misiones PROGRAMADAS")
                if db.query(Mision).filter(Mision.vehiculo_activo == 1).first():
                    raise MissionError(
                        "Existe una reserva de vuelo; confirma su aterrizaje antes de iniciar otra misión"
                    )
                try:
                    self.drone.ensure_ready()
                except RuntimeError as exc:
                    raise MissionError(str(exc), 503) from exc
                # Revalidar también rutas históricas anteriores al contrato de ejecución.
                try:
                    route = MisionCreate(
                        nombre=mission.nombre,
                        waypoints=[WaypointBase.model_validate(wp, from_attributes=True) for wp in mission.waypoints],
                    ).waypoints
                    geofences = validate_waypoints_in_db(db, route)
                except ValueError as exc:
                    raise MissionError(str(exc), 422) from exc
                if mission.evitacion_exclusion:
                    error_zona, warnings_zonas = evaluate_route_against_zones(db, route)
                    if error_zona:
                        raise MissionError(error_zona, 422)
                    for warning in warnings_zonas:
                        logger.warning("Misión %s: %s", mission_id, warning)
                if hasattr(self.drone, "set_geofences"):
                    self.drone.set_geofences(geofences)
                mission.estado = "EN_CURSO"
                mission.ejecutado_por = ejecutado_por
                mission.vehiculo_activo = 1
                mission.iniciada_at = datetime.now(UTC)
                mission.waypoints_completados = 0
                mission.error_ejecucion = None
                try:
                    db.commit()
                except IntegrityError as exc:
                    db.rollback()
                    raise MissionError("Otro ejecutor reservó el vehículo") from exc
            self.active_id = mission_id
            self.cancel_event = Event()
            try:
                self.worker = self.thread_factory(
                    target=self._run,
                    args=(mission_id, route, self.cancel_event),
                    daemon=True,
                    name=f"mission-{mission_id}",
                )
                self.worker.start()
            except Exception as exc:
                self.active_id = None
                self._finish(mission_id, "FALLIDA", "No se pudo iniciar el ejecutor", grounded=True)
                raise MissionError("No se pudo iniciar el ejecutor", 503) from exc

    def _progress(self, mission_id, count):
        with self.sessions.begin() as db:
            mission = self._mission(db, mission_id)
            mission.waypoints_completados = count

    def _log_telemetry(self, mission_id: int) -> None:
        try:
            with self.sessions() as db:
                log_drone_snapshot(db, self.drone, mision_id=mission_id)
        except Exception:
            logger.debug("No se pudo registrar muestra de telemetría para misión %s", mission_id, exc_info=True)

    _DIA_A_WEEKDAY = {"lun": 0, "mar": 1, "mie": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6}

    def _program_next_recurrence(self, db, mission):
        """Genera la siguiente misión PROGRAMADA para una misión recurrente finalizada."""
        dias = mission.dias_semana or []
        if not mission.es_recurrente or not dias or not mission.horario_inicio_programado:
            return
        targets = {self._DIA_A_WEEKDAY[d] for d in dias if d in self._DIA_A_WEEKDAY}
        if not targets:
            return
        base = mission.horario_inicio_programado
        # La próxima corrida jamás puede quedar en el pasado: si la base ya
        # quedó atrás (reinicio del servicio, misión atrasada), el conteo
        # arranca desde ahora conservando la hora programada original.
        referencia = max(base, datetime.now(UTC).replace(tzinfo=None))
        siguiente_fecha = None
        for delta in range(0, 8):
            candidata = datetime.combine(
                (referencia + timedelta(days=delta)).date(), base.time()
            )
            if candidata > referencia and candidata.weekday() in targets:
                siguiente_fecha = candidata
                break
        if siguiente_fecha is None:
            return
        siguiente = Mision(
            creado_por=mission.creado_por,
            nombre=mission.nombre,
            descripcion=mission.descripcion,
            estado="PROGRAMADA",
            horario_inicio_programado=siguiente_fecha,
            horario_fin_programado=(
                mission.horario_fin_programado + timedelta(days=(siguiente_fecha - base).days)
                if mission.horario_fin_programado
                else None
            ),
            duracion_estimada_min=mission.duracion_estimada_min,
            helipuerto_salida=mission.helipuerto_salida,
            helipuerto_llegada=mission.helipuerto_llegada,
            es_recurrente=True,
            dias_semana_json=mission.dias_semana_json,
            evitacion_exclusion=mission.evitacion_exclusion,
            bateria_minima_pct=mission.bateria_minima_pct,
            sensor_optico=mission.sensor_optico,
        )
        db.add(siguiente)
        db.flush()
        for wp in mission.waypoints:
            db.add(
                Ruta(
                    mision_id=siguiente.id,
                    orden_waypoint=wp.orden_waypoint,
                    latitud=wp.latitud,
                    longitud=wp.longitud,
                    altitud_metros=wp.altitud_metros,
                    hover_segundos=wp.hover_segundos,
                )
            )
        logger.info(
            "Misión recurrente %s regenerada como misión %s para %s",
            mission.id,
            siguiente.id,
            siguiente_fecha,
        )

    def _seal_bitacora(self, db, mission):
        """Inserta el registro sellado de bitácora al concluir la misión.

        `BitacoraVuelo` encadena el hash SHA-256 vía `before_insert` y es
        inmutable (UPDATE/DELETE prohibidos): una misión con bitácora pasa a
        ser archivo histórico permanente. Solo se sella una vez por misión.
        """
        if db.query(BitacoraVuelo).filter(BitacoraVuelo.vuelo_id == mission.id).first():
            return
        inicio = mission.iniciada_at or mission.created_at or datetime.now(UTC)
        fin = mission.finalizada_at or datetime.now(UTC)
        inicio = inicio.replace(tzinfo=None) if inicio.tzinfo else inicio
        fin = fin.replace(tzinfo=None) if fin.tzinfo else fin
        duracion = max(0, int((fin - inicio).total_seconds()))

        muestras = db.query(TelemetriaVuelo).filter(TelemetriaVuelo.mision_id == mission.id).all()
        resumen_telemetria = None
        if muestras:
            altitudes = [float(m.altitud_metros) for m in muestras if m.altitud_metros is not None]
            baterias = [float(m.bateria_porcentaje) for m in muestras if m.bateria_porcentaje is not None]
            resumen_telemetria = {
                "muestras": len(muestras),
                "altitud_max_m": max(altitudes) if altitudes else None,
                "bateria_min_pct": min(baterias) if baterias else None,
            }

        partes = []
        detecciones = db.query(Deteccion).filter(Deteccion.vuelo_id == mission.id).all()
        if detecciones:
            conteo = {}
            for det in detecciones:
                conteo[det.tipo] = conteo.get(det.tipo, 0) + 1
            resumen_det = ", ".join(f"{tipo}: {n}" for tipo, n in sorted(conteo.items()))
            partes.append(f"{len(detecciones)} detecciones ({resumen_det})")
        if mission.error_ejecucion:
            partes.append(mission.error_ejecucion)

        db.add(
            BitacoraVuelo(
                vuelo_id=mission.id,
                operador_id=mission.ejecutado_por or mission.creado_por,
                fecha_inicio=inicio,
                fecha_fin=fin,
                duracion_segundos=duracion,
                estado_final=mission.estado,
                incidentes=" | ".join(partes) or None,
                resumen_telemetria=resumen_telemetria,
            )
        )

    def _finish(self, mission_id, state, error=None, *, grounded):
        with self.sessions.begin() as db:
            mission = self._mission(db, mission_id)
            mission.estado = state
            mission.error_ejecucion = error
            mission.finalizada_at = datetime.now(UTC) if grounded else None
            if grounded:
                mission.vehiculo_activo = None
            if state in ("FINALIZADA", "CANCELADA", "FALLIDA"):
                try:
                    self._seal_bitacora(db, mission)
                except Exception:
                    logger.exception("No se pudo sellar la bitácora de la misión %s", mission_id)
            if state in ("FINALIZADA", "FALLIDA"):
                try:
                    self._program_next_recurrence(db, mission)
                except Exception:
                    logger.exception("No se pudo programar la siguiente recurrencia de la misión %s", mission_id)

    def _run(self, mission_id, route, cancel):
        state, error, grounded = "FINALIZADA", None, False
        try:
            if not self.drone.arm_and_takeoff(route[0].altitud_metros, cancel=cancel):
                raise RuntimeError("Despegue rechazado")
            self._log_telemetry(mission_id)
            for count, waypoint in enumerate(route, 1):
                if cancel.is_set():
                    raise FlightCancelled("Cancelación solicitada")
                self.drone.goto_waypoint(waypoint, cancel=cancel)
                hover = float(getattr(waypoint, "hover_segundos", 0.0) or 0.0)
                if hover > 0 and cancel.wait(hover):
                    raise FlightCancelled("Cancelación solicitada")
                self._progress(mission_id, count)
                self._log_telemetry(mission_id)
        except FlightCancelled:
            state = "CANCELADA"
        except Exception:
            logger.exception("Fallo durante la misión %s", mission_id)
            state, error = "FALLIDA", "Error durante la ejecución; consulta los registros del servidor"
        finally:
            # No liberar el vehículo hasta confirmar telemetría reciente, altura y desarmado.
            try:
                if not self.drone.is_grounded():
                    if not self.drone.return_to_launch():
                        raise RuntimeError("RTL rechazado")
                    self.drone.wait_landed()
                grounded = True
            except Exception:
                logger.exception("No se pudo confirmar el aterrizaje de la misión %s", mission_id)
                state, error = "RECUPERACION", "Aterrizaje no confirmado; se mantiene la reserva del vehículo"
            with self.lock:
                if cancel.is_set() and state == "FINALIZADA":
                    state = "CANCELADA"
                try:
                    self._finish(mission_id, state, error, grounded=grounded)
                    self._log_telemetry(mission_id)
                except Exception:
                    logger.exception("No se pudo persistir el cierre de la misión %s; revisar su reserva", mission_id)
                finally:
                    self.active_id = None

    def cancel(self, mission_id):
        with self.lock, self.sessions.begin() as db:
            mission = self._mission(db, mission_id)
            if mission.estado == "PROGRAMADA":
                mission.estado = "CANCELADA"
                mission.finalizada_at = datetime.now(UTC)
            elif mission.estado in ("EN_CURSO", "CANCELANDO") and self.active_id == mission_id:
                mission.estado = "CANCELANDO"
                self.cancel_event.set()
            else:
                raise MissionError(f"La misión no puede cancelarse desde el estado {mission.estado}", 400)

    def confirm_landed(self, mission_id):
        with self.lock, self.sessions.begin() as db:
            mission = self._mission(db, mission_id)
            if self.active_id is not None or self.manual_busy:
                raise MissionError("El ejecutor todavía está activo")
            if mission.vehiculo_activo != 1:
                raise MissionError("La misión no tiene una reserva pendiente")
            try:
                self.drone.ensure_ready()
            except RuntimeError as exc:
                raise MissionError(str(exc), 503) from exc
            mission.estado = "FALLIDA"
            mission.error_ejecucion = "Ejecución interrumpida; aterrizaje confirmado por el operador"
            mission.finalizada_at = datetime.now(UTC)
            mission.vehiculo_activo = None
            try:
                self._seal_bitacora(db, mission)
            except Exception:
                logger.exception("No se pudo sellar la bitácora de la misión %s", mission_id)

    @contextmanager
    def manual_control(self, *, allow_reserved=False):
        with self.lock, self.sessions() as db:
            if self.active_id is not None or self.manual_busy:
                raise MissionError("El vehículo está ocupado")
            if not allow_reserved and db.query(Mision).filter(Mision.vehiculo_activo == 1).first():
                raise MissionError("Hay una misión con reserva pendiente")
            self.manual_busy = True
        try:
            yield
        finally:
            with self.lock:
                self.manual_busy = False

    def emergency_rtl(self, send_rtl):
        with self.lock:
            if self.active_id is not None:
                self.cancel(self.active_id)
                return True
            return send_rtl()

    def run_due(self, now=None):
        now = now or datetime.now(UTC)
        now = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
        with self.sessions() as db:
            ids = [
                row.id
                for row in db.query(Mision)
                .filter(
                    Mision.estado == "PROGRAMADA",
                    Mision.horario_inicio_programado <= now,
                )
                .order_by(Mision.horario_inicio_programado, Mision.id)
                .limit(20)
                .all()
            ]
        for mission_id in ids:
            if self.stop_event.is_set():
                return
            try:
                self.start(mission_id)
                return
            except MissionError as exc:
                if exc.status_code != 422:
                    return  # Ocupado o sin conexión: reintentar en el próximo ciclo.
                logger.warning("Misión %s con ruta inválida: %s", mission_id, exc)

    def start_scheduler(self, interval=5):
        self.stop_event.clear()

        def poll():
            while not self.stop_event.is_set():
                try:
                    self.run_due()
                except Exception:
                    logger.exception("Error al consultar misiones programadas")
                self.stop_event.wait(interval)

        self.scheduler = Thread(target=poll, name="mission-scheduler", daemon=True)
        self.scheduler.start()

    def is_scheduler_running(self) -> bool:
        return (
            self.scheduler is not None
            and self.scheduler.is_alive()
            and not self.stop_event.is_set()
        )

    def set_scheduler_enabled(self, enabled: bool) -> dict:
        """Enciende/apaga el scheduler autónomo sin afectar una misión en curso."""
        if enabled:
            if not self.is_scheduler_running():
                self.start_scheduler()
        else:
            self.stop_event.set()
            if self.scheduler is not None:
                self.scheduler.join(timeout=5)
                self.scheduler = None
        return {"enabled": self.is_scheduler_running()}

    def scheduler_status(self) -> dict:
        with self.sessions() as db:
            programmed = (
                db.query(Mision).filter(Mision.estado == "PROGRAMADA").count()
            )
        return {
            "enabled": self.is_scheduler_running(),
            "running": self.is_scheduler_running(),
            "programmed_count": programmed,
        }

    def shutdown(self):
        self.stop_event.set()
        with self.lock:
            if self.active_id is not None:
                self.cancel_event.set()
        if self.scheduler:
            self.scheduler.join(timeout=5)
        if self.worker:
            self.worker.join(timeout=10)
        # Si el proceso termina antes del aterrizaje, la reserva permanece para recuperación manual.


mission_service = MissionService()


def get_mission_service():
    return mission_service
