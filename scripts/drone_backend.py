"""Script autónomo de circuito cerrado con límites normativos de altitud, peso y horario."""

# --- Parche de compatibilidad Python 3.10+ para DroneKit ---
import collections
import collections.abc

collections.MutableMapping = collections.abc.MutableMapping
collections.Mapping = collections.abc.Mapping
collections.Iterable = collections.abc.Iterable
# ------------------------------------------------------------

import argparse
import math
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.normative import validate_altitude, validate_operating_window, validate_weight  # noqa: E402


def validate_flight_plan(
    *,
    altitude_m: float,
    weight_kg: float,
    flight_time: datetime | None = None,
) -> None:
    """Valida límites normativos antes de enviar comandos al dron."""
    validate_altitude(altitude_m)
    validate_weight(weight_kg)
    validate_operating_window(flight_time or datetime.now())


def get_location_metres(original_location, d_north: float, d_east: float):
    """Devuelve LocationGlobalRelative desplazada d_north/d_east metros."""
    from dronekit import LocationGlobalRelative

    earth_radius = 6378137.0
    d_lat = d_north / earth_radius
    d_lon = d_east / (earth_radius * math.cos(math.pi * original_location.lat / 180))
    new_lat = original_location.lat + (d_lat * 180 / math.pi)
    new_lon = original_location.lon + (d_lon * 180 / math.pi)
    return LocationGlobalRelative(new_lat, new_lon, original_location.alt)


def arm_and_takeoff(vehicle, target_altitude: float) -> None:
    """Arma el vehículo en modo GUIDED y asciende a la altitud normativa validada."""
    validate_altitude(target_altitude)
    while not vehicle.is_armable:
        time.sleep(1)
    while vehicle.gps_0.fix_type < 3:
        time.sleep(1)
    while vehicle.mode.name != "GUIDED":
        vehicle._master.mav.set_mode_send(vehicle._master.target_system, 209, 4)
        time.sleep(1)
    while not vehicle.armed:
        vehicle.armed = True
        time.sleep(1)

    time.sleep(2)
    vehicle.simple_takeoff(target_altitude)
    while True:
        if vehicle.location.global_relative_frame.alt >= target_altitude * 0.95:
            break
        time.sleep(1)


def run_flight(
    *,
    connection_string: str = "127.0.0.1:14550",
    target_altitude: float = 10.0,
    weight_kg: float = 2.5,
) -> None:
    """Ejecuta un circuito cerrado validando límites normativos previo al despegue."""
    validate_flight_plan(altitude_m=target_altitude, weight_kg=weight_kg)

    from dronekit import connect

    vehicle = connect(connection_string, wait_ready=True)
    try:
        vehicle.parameters["FENCE_ENABLE"] = 0
        vehicle.parameters["ARMING_CHECK"] = 0
        vehicle._master.mav.command_long_send(
            vehicle._master.target_system,
            vehicle._master.target_component,
            179,
            0,
            0,
            0,
            0,
            0,
            20.70428,
            -100.44358,
            1900,
        )
        time.sleep(2)

        arm_and_takeoff(vehicle, target_altitude)
        time.sleep(5)

        current_loc = vehicle.location.global_relative_frame
        waypoint1 = get_location_metres(current_loc, d_north=200, d_east=30)
        vehicle.simple_goto(waypoint1)
        time.sleep(50)

        vehicle._master.mav.set_mode_send(vehicle._master.target_system, 209, 6)
    finally:
        vehicle.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Script de circuito cerrado con límites normativos")
    parser.add_argument("--connection", default="127.0.0.1:14550")
    parser.add_argument("--altitude", type=float, default=10.0)
    parser.add_argument("--weight", type=float, default=2.5)
    parser.add_argument("--dry-run", action="store_true", help="Solo valida límites normativos sin conectar al dron")
    args = parser.parse_args()

    if args.dry_run:
        validate_flight_plan(altitude_m=args.altitude, weight_kg=args.weight)
        print("Validación normativa exitosa")
        return

    run_flight(connection_string=args.connection, target_altitude=args.altitude, weight_kg=args.weight)


if __name__ == "__main__":
    main()
