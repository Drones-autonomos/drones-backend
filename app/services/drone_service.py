# --- Parche de compatibilidad Python 3.10+ para DroneKit ---
import collections
import collections.abc
import logging
import math
import time

from app.core.normative import validate_altitude
from app.services.geofence_service import GeofenceSpec, validate_point_against_specs

collections.MutableMapping = collections.abc.MutableMapping
collections.Mapping = collections.abc.Mapping
collections.Iterable = collections.abc.Iterable
# ------------------------------------------------------------

logger = logging.getLogger(__name__)

# dronekit es una dependencia opcional de simulación.
# Se importa de forma lazy para que el servidor FastAPI pueda arrancar
# en entornos sin dronekit (producción, CI, tests).
try:
    import collections
    import collections.abc

    # Parche para compatibilidad de dronekit con Python 3.10+
    collections.MutableMapping = collections.abc.MutableMapping

    from dronekit import LocationGlobalRelative, VehicleMode
    from dronekit import connect as dronekit_connect

    _DRONEKIT_AVAILABLE = True
except ImportError:
    _DRONEKIT_AVAILABLE = False
    logger.warning(
        "dronekit no está instalado — los endpoints de control de vuelo "
        "estarán deshabilitados. Instálalo con: pip install dronekit"
    )


def _require_dronekit():
    if not _DRONEKIT_AVAILABLE:
        raise RuntimeError("dronekit no está instalado. Ejecuta: pip install dronekit  (requiere entorno SITL)")


# Modos custom de ArduCopter para set_mode_send en MAVLink crudo.
# El SITL copter-3.3 rechaza MAV_CMD_DO_SET_MODE (ver scripts/drone_backend.py);
# enviamos ambos comandos para cubrir firmware antiguo y nuevo.
_COPTER_MODES = {"GUIDED": 4, "LOITER": 5, "RTL": 6, "LAND": 9, "BRAKE": 17}


class _Waypoint:
    """Waypoint mínimo compatible con goto_waypoint (latitud/longitud/altitud_metros)."""

    __slots__ = ("latitud", "longitud", "altitud_metros")

    def __init__(self, latitud: float, longitud: float, altitud_metros: float) -> None:
        self.latitud = latitud
        self.longitud = longitud
        self.altitud_metros = altitud_metros


class FlightCancelled(RuntimeError):
    """La navegación se interrumpió antes de emitir el siguiente comando."""


class SignalLossError(RuntimeError):
    """Se perdió el enlace MAVLink/heartbeat con el vehículo."""


class DroneService:
    def __init__(self, *, poll_interval=0.25, clock=time.monotonic, sleep=time.sleep):
        self.vehicle = None
        self.poll_interval = poll_interval
        self.clock = clock
        self.sleep = sleep
        self.active_geofences: list[GeofenceSpec] = []
        self.paused = False
        self._paused_target = None

    def set_geofences(self, geofences: list[GeofenceSpec]) -> None:
        self.active_geofences = list(geofences)

    def ensure_connected(self):
        _require_dronekit()
        if self.vehicle is None:
            raise RuntimeError("Dron no conectado")
        heartbeat = self.vehicle.last_heartbeat
        if heartbeat is None or not math.isfinite(heartbeat) or heartbeat > 5:
            raise SignalLossError("Telemetría del dron ausente o desactualizada (pérdida de señal)")

    def configure_gcs_failsafe(self, *, enabled: bool = True) -> dict:
        """Configura el failsafe de pérdida de enlace GCS en ArduPilot (FS_GCS_ENABLE=1 -> RTL)."""
        self.ensure_connected()
        params = getattr(self.vehicle, "parameters", None)
        value = 1 if enabled else 0
        if params is not None:
            params["FS_GCS_ENABLE"] = value
        return {"fs_gcs_enable": value, "accion_perdida_enlace": "RTL" if enabled else "DESACTIVADO"}

    def is_grounded(self):
        self.ensure_connected()
        altitude = self.vehicle.location.global_relative_frame.alt
        return not self.vehicle.armed and altitude is not None and math.isfinite(altitude) and abs(altitude) <= 1.0

    def ensure_ready(self):
        if not self.is_grounded():
            raise RuntimeError("El dron debe estar desarmado y en tierra para iniciar una misión")

    def _wait(self, predicate, timeout, description, cancel=None, guided=False):
        deadline = self.clock() + timeout
        while True:
            self.ensure_connected()
            if cancel is not None and cancel.is_set():
                raise FlightCancelled("Cancelación solicitada")
            if guided and self.vehicle.mode.name != "GUIDED":
                if self.paused:
                    # Mientras el operador mantenga la pausa el timeout no corre.
                    deadline = self.clock() + timeout
                else:
                    raise RuntimeError("El vehículo abandonó el modo GUIDED")
            if predicate():
                return
            if self.clock() >= deadline:
                raise TimeoutError(f"Tiempo agotado: {description}")
            self.sleep(self.poll_interval)

    def connect(self, connection_string: str = "127.0.0.1:14550") -> bool:
        _require_dronekit()
        if self.vehicle:
            try:
                self.ensure_connected()
                return True
            except Exception:
                # Vehículo con heartbeat muerto (SITL reiniciado, enlace caído):
                # liberarlo para poder reconectar; si no, el objeto obsoleto
                # bloquea cualquier intento posterior de conexión.
                self.close()
        try:
            self.vehicle = dronekit_connect(connection_string, wait_ready=True, timeout=30, heartbeat_timeout=15)
            return True
        except Exception:
            logger.exception("No se pudo conectar al dron")
            return False

    def _set_mode(self, name: str) -> None:
        self.vehicle.mode = VehicleMode(name)
        master = getattr(self.vehicle, "_master", None)
        custom_mode = _COPTER_MODES.get(name)
        if master is not None and custom_mode is not None:
            master.mav.set_mode_send(master.target_system, 209, custom_mode)

    def arm_and_takeoff(self, target_altitude: float, cancel=None, timeout=90) -> bool:
        self.ensure_ready()
        validate_altitude(target_altitude)
        self._wait(lambda: self.vehicle.is_armable, timeout, "prearmado", cancel)
        self._set_mode("GUIDED")
        self._wait(lambda: self.vehicle.mode.name == "GUIDED", timeout, "modo GUIDED", cancel)
        self.vehicle.armed = True
        self._wait(lambda: self.vehicle.armed, timeout, "armado", cancel, guided=True)
        self.vehicle.simple_takeoff(target_altitude)
        self._wait(
            lambda: (
                self.vehicle.location.global_relative_frame.alt is not None
                and self.vehicle.location.global_relative_frame.alt >= target_altitude * 0.95
            ),
            timeout,
            "despegue",
            cancel,
            guided=True,
        )
        return True

    def goto_waypoint(self, waypoint, cancel=None, timeout=180):
        self.ensure_connected()
        validate_altitude(waypoint.altitud_metros)
        validate_point_against_specs(
            float(waypoint.latitud),
            float(waypoint.longitud),
            float(waypoint.altitud_metros),
            self.active_geofences,
        )
        if cancel is not None and cancel.is_set():
            raise FlightCancelled("Cancelación solicitada")
        if not self.vehicle.armed or self.vehicle.mode.name != "GUIDED":
            raise RuntimeError("La navegación requiere un vehículo armado en GUIDED")
        target = LocationGlobalRelative(waypoint.latitud, waypoint.longitud, waypoint.altitud_metros)
        self._paused_target = target
        self.vehicle.simple_goto(target)

        def arrived():
            if not self.vehicle.armed:
                raise RuntimeError("El vehículo se desarmó durante la navegación")
            pos = self.vehicle.location.global_relative_frame
            values = (pos.lat, pos.lon, pos.alt)
            if any(value is None or not math.isfinite(value) for value in values):
                return False
            lat1, lat2 = math.radians(pos.lat), math.radians(waypoint.latitud)
            dlat = lat2 - lat1
            dlon = math.radians(waypoint.longitud - pos.lon)
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            distance = 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, a))))
            return distance <= 3 and abs(pos.alt - waypoint.altitud_metros) <= 1

        self._wait(arrived, timeout, "llegada al waypoint", cancel, guided=True)

    def pause_flight(self) -> dict:
        """Detiene el avance sosteniendo posición (BRAKE, con LOITER como respaldo)."""
        self.ensure_connected()
        if not self.vehicle.armed:
            raise RuntimeError("No hay un vuelo activo que pausar")
        hold_mode = None
        for candidate in ("BRAKE", "LOITER"):
            self._set_mode(candidate)
            try:
                self._wait(
                    lambda mode_name=candidate: self.vehicle.mode.name == mode_name,
                    5,
                    f"modo {candidate}",
                )
                hold_mode = candidate
                break
            except TimeoutError:
                continue
        if hold_mode is None:
            raise RuntimeError("El vehículo no aceptó el modo de espera (BRAKE/LOITER)")
        self.paused = True
        return {"pausado": True, "modo": hold_mode}

    def resume_flight(self) -> dict:
        """Reanuda el vuelo pausado: vuelve a GUIDED y reemite el waypoint en curso."""
        self.ensure_connected()
        if not self.paused:
            return {"pausado": False, "modo": getattr(self.vehicle.mode, "name", None)}
        self._set_mode("GUIDED")
        self._wait(lambda: self.vehicle.mode.name == "GUIDED", 10, "modo GUIDED")
        self.paused = False
        if self._paused_target is not None:
            self.vehicle.simple_goto(self._paused_target)
        return {"pausado": False, "modo": "GUIDED"}

    def emergency_stop(self) -> dict:
        """Parada de emergencia: aterriza en el punto actual (LAND) sin esperar la misión."""
        self.ensure_connected()
        self.paused = False
        self._paused_target = None
        self._set_mode("LAND")
        self._wait(lambda: self.vehicle.mode.name == "LAND", 10, "modo LAND")
        return {"detenido": True, "modo": "LAND"}

    def get_failsafe_status(self) -> dict:
        """Estado del failsafe de pérdida de enlace GCS (FS_GCS_ENABLE)."""
        connected = self.vehicle is not None
        enabled = None
        if connected:
            params = getattr(self.vehicle, "parameters", None)
            if params is not None:
                try:
                    enabled = bool(int(float(params.get("FS_GCS_ENABLE", 0))))
                except (TypeError, ValueError):
                    enabled = None
        return {"connected": connected, "enabled": enabled}

    def preflight_check(self) -> dict:
        """Verificación prevuelo: no lanza si el dron está desconectado, solo reporta."""
        checks: dict[str, bool] = {}
        detalles: dict = {}
        connected = self.vehicle is not None
        checks["conexion"] = connected
        if not connected:
            checks.update({"enlace": False, "armable": False, "bateria": False, "gps": False})
            return {"ready": False, "checks": checks, "detalles": detalles}

        heartbeat = getattr(self.vehicle, "last_heartbeat", None)
        enlace = heartbeat is not None and math.isfinite(heartbeat) and heartbeat <= 5
        checks["enlace"] = enlace
        detalles["heartbeat_age_s"] = heartbeat

        armable = bool(getattr(self.vehicle, "is_armable", False))
        checks["armable"] = armable

        battery = getattr(self.vehicle, "battery", None)
        level = getattr(battery, "level", None)
        checks["bateria"] = level is not None and level >= 30
        detalles["bateria_porcentaje"] = level

        gps = getattr(self.vehicle, "gps_0", None)
        fix = getattr(gps, "fix_type", None)
        checks["gps"] = fix is not None and fix >= 3
        detalles["gps_fix_type"] = fix
        detalles["satelites"] = getattr(gps, "satellites_visible", None)

        failsafe = self.get_failsafe_status()["enabled"]
        detalles["failsafe_gcs"] = failsafe
        detalles["modo"] = getattr(getattr(self.vehicle, "mode", None), "name", None)
        detalles["armado"] = bool(getattr(self.vehicle, "armed", False))
        detalles["geocercas_cargadas"] = len(self.active_geofences)

        ready = all(checks.values())
        return {"ready": ready, "checks": checks, "detalles": detalles}

    def return_to_launch(self) -> bool:
        self.ensure_connected()
        self.paused = False
        self._paused_target = None
        self._set_mode("RTL")
        return True

    def return_to_heliport(
        self,
        lat: float,
        lon: float,
        *,
        alt: float | None = None,
        cancel=None,
        timeout: float = 180,
    ) -> dict:
        """RTL hacia un helipuerto alterno: navega en GUIDED al pad y aterriza con LAND.

        ArduPilot RTL siempre regresa al punto HOME; para aterrizar en otra
        estación se navega hasta sus coordenadas y luego se conmuta a LAND.
        Bloqueante: está pensado para correr en un hilo aparte del endpoint.
        """
        self.ensure_connected()
        if not self.vehicle.armed:
            raise RuntimeError("No hay un vuelo activo para redirigir al helipuerto")
        self.paused = False
        self._paused_target = None
        frame = self.vehicle.location.global_relative_frame
        cruise_alt = alt if alt is not None else (frame.alt or 15.0)
        # Reintenta el retorno a GUIDED: el ejecutor de misión pudo haber
        # enviado un RTL residual justo antes de liberar el vehículo.
        last_exc: Exception | None = None
        for _ in range(3):
            try:
                if self.vehicle.mode.name != "GUIDED":
                    self._set_mode("GUIDED")
                    self._wait(lambda: self.vehicle.mode.name == "GUIDED", 10, "modo GUIDED", cancel)
                break
            except TimeoutError as exc:
                last_exc = exc
        else:
            raise last_exc or TimeoutError("El vehículo no aceptó el modo GUIDED")
        waypoint = _Waypoint(latitud=float(lat), longitud=float(lon), altitud_metros=float(cruise_alt))
        self.goto_waypoint(waypoint, cancel=cancel, timeout=timeout)
        self._set_mode("LAND")
        self._wait(lambda: self.vehicle.mode.name == "LAND", 10, "modo LAND", cancel)
        return {"aterrizando": True, "helipuerto_lat": lat, "helipuerto_lon": lon}

    def wait_landed(self, timeout=180):
        self._wait(self.is_grounded, timeout, "aterrizaje y desarmado")

    def close(self) -> None:
        if self.vehicle:
            self.vehicle.close()
            self.vehicle = None
        self.paused = False
        self._paused_target = None


# Instancia global del servicio
drone_service = DroneService()
