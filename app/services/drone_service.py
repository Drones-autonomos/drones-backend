import logging
import time

logger = logging.getLogger(__name__)

# dronekit es una dependencia opcional de simulación.
# Se importa de forma lazy para que el servidor FastAPI pueda arrancar
# en entornos sin dronekit (producción, CI, tests).
try:
    import collections
    import collections.abc

    # Parche para compatibilidad de dronekit con Python 3.10+
    collections.MutableMapping = collections.abc.MutableMapping

    from dronekit import VehicleMode
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


class DroneService:
    def __init__(self):
        self.vehicle = None

    def connect(self, connection_string: str = "127.0.0.1:14550") -> bool:
        _require_dronekit()
        if self.vehicle:
            logger.info("El vehículo ya está conectado.")
            return True
        try:
            logger.info(f"Conectando al vehículo en: {connection_string}")
            self.vehicle = dronekit_connect(connection_string, wait_ready=True)
            logger.info("Conexión exitosa.")
            return True
        except Exception as e:
            logger.error(f"Error al conectar con el dron: {e}")
            return False

    def arm_and_takeoff(self, target_altitude: float) -> bool:
        _require_dronekit()
        if not self.vehicle:
            logger.error("Vehículo no conectado.")
            return False

        logger.info("Iniciando chequeos pre-armado básicos")
        while not self.vehicle.is_armable:
            logger.info(" Esperando a que el vehículo se inicialice...")
            time.sleep(1)

        logger.info("Armando motores")
        self.vehicle.mode = VehicleMode("GUIDED")
        self.vehicle.armed = True

        while not self.vehicle.armed:
            logger.info(" Esperando armado...")
            time.sleep(1)

        logger.info("¡Despegando!")
        self.vehicle.simple_takeoff(target_altitude)

        while True:
            alt = self.vehicle.location.global_relative_frame.alt
            logger.info(f" Altitud: {alt}")
            if alt >= target_altitude * 0.95:
                logger.info("Altitud objetivo alcanzada")
                break
            time.sleep(1)
        return True

    def return_to_launch(self) -> bool:
        _require_dronekit()
        if not self.vehicle:
            logger.error("Vehículo no conectado.")
            return False
        logger.info("Regresando a base (RTL)")
        self.vehicle.mode = VehicleMode("RTL")
        return True

    def close(self) -> None:
        if self.vehicle:
            logger.info("Cerrando conexión con el vehículo")
            self.vehicle.close()
            self.vehicle = None


# Instancia global del servicio
drone_service = DroneService()
