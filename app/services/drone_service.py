import time
import logging
from dronekit import connect as dronekit_connect, VehicleMode

logger = logging.getLogger(__name__)

class DroneService:
    def __init__(self):
        self.vehicle = None

    def connect(self, connection_string="127.0.0.1:14550"):
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

    def arm_and_takeoff(self, target_altitude):
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
            logger.info(f" Altitud: {self.vehicle.location.global_relative_frame.alt}")
            if self.vehicle.location.global_relative_frame.alt >= target_altitude * 0.95:
                logger.info("Altitud objetivo alcanzada")
                break
            time.sleep(1)
        return True

    def return_to_launch(self):
        if not self.vehicle:
            logger.error("Vehículo no conectado.")
            return False
        logger.info("Regresando a base (RTL)")
        self.vehicle.mode = VehicleMode("RTL")
        return True

    def close(self):
        if self.vehicle:
            logger.info("Cerrando conexión con el vehículo")
            self.vehicle.close()
            self.vehicle = None

# Instancia global del servicio
drone_service = DroneService()
