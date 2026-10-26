"""Orquestación de un vehículo. Ejecutar una sola instancia/worker de control."""

import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Event, RLock, Thread

from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.mission import Mision
from app.schemas.mission import MisionCreate, WaypointBase
from app.services.drone_service import FlightCancelled, drone_service

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

    def start(self, mission_id):
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
                except ValueError as exc:
                    raise MissionError("La ruta guardada no es válida para ejecución", 422) from exc
                mission.estado = "EN_CURSO"
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

    def _finish(self, mission_id, state, error=None, *, grounded):
        with self.sessions.begin() as db:
            mission = self._mission(db, mission_id)
            mission.estado = state
            mission.error_ejecucion = error
            mission.finalizada_at = datetime.now(UTC) if grounded else None
            if grounded:
                mission.vehiculo_activo = None

    def _run(self, mission_id, route, cancel):
        state, error, grounded = "FINALIZADA", None, False
        try:
            if not self.drone.arm_and_takeoff(route[0].altitud_metros, cancel=cancel):
                raise RuntimeError("Despegue rechazado")
            for count, waypoint in enumerate(route, 1):
                if cancel.is_set():
                    raise FlightCancelled("Cancelación solicitada")
                self.drone.goto_waypoint(waypoint, cancel=cancel)
                self._progress(mission_id, count)
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
