"""Simulador de base de carga automatizada en el punto HOME."""

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

from app.services.geofence_service import haversine_distance_m


@dataclass(slots=True)
class ChargingBaseStatus:
    home_lat: float
    home_lon: float
    dock_radius_m: float
    estado: str  # IDLE | DOCKED | CHARGING | CHARGED
    bateria_porcentaje: float
    ciclos_completados: int
    distancia_home_m: float | None
    ultimo_acoplamiento_at: datetime | None


class ChargingBaseService:
    """Gestiona la verificación de aterrizaje en HOME y el ciclo simulado de recarga."""

    def __init__(
        self,
        *,
        home_lat: float = 20.70428,
        home_lon: float = -100.44358,
        dock_radius_m: float = 3.0,
    ) -> None:
        self._lock = Lock()
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.dock_radius_m = dock_radius_m
        self.estado = "IDLE"
        self.bateria_porcentaje = 100.0
        self.ciclos_completados = 0
        self.distancia_home_m: float | None = None
        self.ultimo_acoplamiento_at: datetime | None = None

    def get_status(self) -> dict:
        with self._lock:
            return {
                "home_lat": self.home_lat,
                "home_lon": self.home_lon,
                "dock_radius_m": self.dock_radius_m,
                "estado": self.estado,
                "bateria_porcentaje": self.bateria_porcentaje,
                "ciclos_completados": self.ciclos_completados,
                "distancia_home_m": self.distancia_home_m,
                "ultimo_acoplamiento_at": (
                    self.ultimo_acoplamiento_at.isoformat() if self.ultimo_acoplamiento_at else None
                ),
            }

    def dock_and_recharge(
        self,
        drone,
        *,
        target_pct: float = 100.0,
        step_pct: float = 25.0,
    ) -> dict:
        """Verifica aterrizaje en HOME y ejecuta el ciclo de recarga hasta `target_pct`."""
        with self._lock:
            if not drone.is_grounded():
                raise RuntimeError("El dron debe estar en tierra y desarmado para acoplarse a la base")

            loc = drone.vehicle.location.global_relative_frame
            if loc.lat is None or loc.lon is None:
                raise RuntimeError("Coordenadas del vehículo no disponibles para verificar HOME")

            dist_m = round(haversine_distance_m(float(loc.lat), float(loc.lon), self.home_lat, self.home_lon), 3)
            self.distancia_home_m = dist_m
            if dist_m > self.dock_radius_m:
                raise RuntimeError(f"Fuera de la base de carga HOME ({dist_m:.2f} m > {self.dock_radius_m:.2f} m)")

            battery = getattr(drone.vehicle, "battery", None)
            current = getattr(battery, "level", None)
            self.bateria_porcentaje = float(current) if current is not None else self.bateria_porcentaje
            self.estado = "DOCKED"
            self.ultimo_acoplamiento_at = datetime.now(UTC)

            if self.bateria_porcentaje < target_pct:
                self.estado = "CHARGING"
                while self.bateria_porcentaje < target_pct:
                    self.bateria_porcentaje = min(target_pct, self.bateria_porcentaje + step_pct)
                if battery is not None:
                    try:
                        battery.level = int(round(self.bateria_porcentaje))
                    except Exception:
                        pass

            self.estado = "CHARGED"
            self.ciclos_completados += 1
            return {
                "home_lat": self.home_lat,
                "home_lon": self.home_lon,
                "dock_radius_m": self.dock_radius_m,
                "estado": self.estado,
                "bateria_porcentaje": self.bateria_porcentaje,
                "ciclos_completados": self.ciclos_completados,
                "distancia_home_m": self.distancia_home_m,
                "ultimo_acoplamiento_at": self.ultimo_acoplamiento_at.isoformat(),
            }


charging_base_service = ChargingBaseService()
