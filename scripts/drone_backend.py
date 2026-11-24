"""Script autónomo de circuito cerrado con límites normativos de altitud, peso y horario."""

import argparse
import collections
import collections.abc
import math
import sys
import time
from datetime import datetime
from pathlib import Path

# --- Parche de compatibilidad Python 3.10+ para DroneKit ---
collections.MutableMapping = collections.abc.MutableMapping
collections.Mapping = collections.abc.Mapping
collections.Iterable = collections.abc.Iterable
# ------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.normative import validate_altitude, validate_operating_window, validate_weight  # noqa: E402

# RUTA_BARRIDO y ZONAS_INTERFERENCIA se re-exportan a propósito: los tests los
# leen como patrol.RUTA_BARRIDO / patrol.ZONAS_INTERFERENCIA (noqa: F401).
from app.core.patrol_routes import (  # noqa: E402
    ALT_RECORRIDO_M,
    BASE_1_COORDS,
    BASE_2_COORDS,
    EARTH_RADIUS_M,
    HOME_COORDS,
    RUTA_BARRIDO,  # noqa: F401
    RUTA_REGRESO,
    RUTA_TRASLADO,
    RUTAS_BARRIDO,
    ZONAS_INTERFERENCIA,  # noqa: F401
    validar_ruta,
)


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


# ---------------- Plan de vuelo en coordenadas GPS reales --------------------
# Las coordenadas de rutas, zonas de interferencia y validar_ruta() viven en
# app/core/patrol_routes.py (fuente única compartida con GET /missions/presets
# y el fallback offline del frontend). Se importan arriba junto a normative.

ALT_BASE_M = 6.0  # altura de "acoplamiento" sobre cada base
VEL_TRANSITO = 8.0  # m/s en regreso entre bases
VEL_BARRIDO = 6.0  # m/s durante el reconocimiento
DIST_LLEGADA_M = 4.0
TOL_ALT_M = 1.5
TIMEOUT_TRAMO_S = 180
REINTENTO_DESTINO_S = 5.0
MAX_HEARTBEAT_S = 5.0


def distancia_metres(a, b) -> float:
    """Distancia horizontal en metros entre dos LocationGlobal(Relative)."""
    d_north = math.radians(b.lat - a.lat) * EARTH_RADIUS_M
    d_east = math.radians(b.lon - a.lon) * EARTH_RADIUS_M * math.cos(math.pi * a.lat / 180)
    return math.hypot(d_north, d_east)


def volar_a(
    vehicle,
    coords: tuple[float, float],
    alt_m: float,
    velocidad: float,
    etiqueta: str,
) -> None:
    """Navega a las coordenadas GPS (lat, lon) indicadas y espera a alcanzarlas."""
    from dronekit import LocationGlobalRelative

    validate_altitude(alt_m)
    destino = LocationGlobalRelative(coords[0], coords[1], alt_m)
    t0 = time.monotonic()
    ultimo_envio = None
    while True:
        if vehicle.last_heartbeat is None or vehicle.last_heartbeat > MAX_HEARTBEAT_S:
            raise RuntimeError(f"Telemetría desactualizada en {etiqueta}; misión interrumpida")
        if not vehicle.armed or vehicle.mode.name != "GUIDED":
            raise RuntimeError(f"Control GUIDED no disponible en {etiqueta}; misión interrumpida")
        ahora = time.monotonic()
        actual = vehicle.location.global_relative_frame
        restante = distancia_metres(actual, destino)
        if restante <= DIST_LLEGADA_M and abs(actual.alt - alt_m) <= TOL_ALT_M:
            print(f"  ✓ {etiqueta} alcanzado                    ")
            return
        if ahora - t0 > TIMEOUT_TRAMO_S:
            raise TimeoutError(f"Timeout en {etiqueta} ({restante:.0f} m); no se avanzará al siguiente punto")
        if ultimo_envio is None or ahora - ultimo_envio >= REINTENTO_DESTINO_S:
            if ultimo_envio is not None:
                print(f"  Reenviando destino {etiqueta} ({restante:.0f} m pendientes)")
            vehicle.simple_goto(destino, groundspeed=velocidad)
            ultimo_envio = ahora
        print(f"  → {etiqueta}: {restante:.0f} m   ", end="\r", flush=True)
        time.sleep(1)


def run_flight(
    *,
    connection_string: str = "127.0.0.1:14550",
    target_altitude: float = ALT_RECORRIDO_M,
    weight_kg: float = 2.5,
    nombre_ruta: str = "clasica",
) -> None:
    """Patrullaje: Base 1 → barrido evitando interferencias → Base 2 → Base 1."""
    validate_flight_plan(altitude_m=target_altitude, weight_kg=weight_kg)
    validate_altitude(ALT_BASE_M)
    clareo_m, longitud_m = validar_ruta(nombre_ruta=nombre_ruta)
    barrido = RUTAS_BARRIDO[nombre_ruta]
    print(
        f"Ruta {nombre_ruta} validada: {longitud_m:.0f} m, "
        f"clareo mínimo a interferencias {clareo_m:.1f} m, altitud relativa {target_altitude:.0f} m"
    )

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
            HOME_COORDS[0],
            HOME_COORDS[1],
            1900,
        )
        time.sleep(2)

        arm_and_takeoff(vehicle, target_altitude)

        print("1/4 Reconocimiento en ruta hacia Base 1")
        for i, punto in enumerate(RUTA_TRASLADO, 1):
            volar_a(vehicle, punto, target_altitude, VEL_BARRIDO, f"traslado {i}/{len(RUTA_TRASLADO)}")
        volar_a(vehicle, BASE_1_COORDS, target_altitude, VEL_BARRIDO, "Base 1")

        print("2/4 Barrido de reconocimiento Base 1 → Base 2")
        for i, punto in enumerate(barrido, 1):
            volar_a(vehicle, (punto[0], punto[1]), target_altitude, VEL_BARRIDO, f"tramo {i}/{len(barrido)}")
            if len(punto) > 2:
                print(f"    inspeccionando zona {punto[2]:.0f} s...")
                time.sleep(punto[2])
        volar_a(vehicle, BASE_2_COORDS, target_altitude, VEL_BARRIDO, "Base 2")

        print(f"3/4 Pausa sobre Base 2 a {target_altitude:.0f} m (sin descenso)")
        time.sleep(4)

        print("4/4 Regreso Base 2 → Base 1")
        for i, punto in enumerate(RUTA_REGRESO, 1):
            volar_a(vehicle, punto, target_altitude, VEL_TRANSITO, f"regreso {i}/{len(RUTA_REGRESO)}")
        volar_a(vehicle, BASE_1_COORDS, target_altitude, VEL_TRANSITO, "Base 1")
        volar_a(vehicle, BASE_1_COORDS, ALT_BASE_M, VEL_BARRIDO, "descenso a Base 1")

        print("Aterrizando en Base 1 (modo LAND)")
        vehicle._master.mav.set_mode_send(vehicle._master.target_system, 209, 9)
        while vehicle.location.global_relative_frame.alt > 0.5:
            time.sleep(1)
        while vehicle.armed:
            vehicle.armed = False
            time.sleep(1)
        print("Misión completada — dron acoplado en Base 1")
    finally:
        vehicle.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Patrullaje B1→barrido→B2→B1 con límites normativos")
    parser.add_argument("--connection", default="127.0.0.1:14550")
    parser.add_argument("--altitude", type=float, default=ALT_RECORRIDO_M, help="Altitud relativa de recorrido (30 m)")
    parser.add_argument("--weight", type=float, default=2.5)
    parser.add_argument(
        "--ruta",
        choices=RUTAS_BARRIDO,
        default="clasica",
        help="clasica: barrido original; interior: corredor este y plaza norte; canchas: sector sur y canchas",
    )
    parser.add_argument("--dry-run", action="store_true", help="Solo valida normativa y ruta sin conectar al dron")
    args = parser.parse_args()

    if args.dry_run:
        validate_flight_plan(altitude_m=args.altitude, weight_kg=args.weight)
        validate_altitude(ALT_BASE_M)
        clareo_m, longitud_m = validar_ruta(nombre_ruta=args.ruta)
        print(
            f"Validación normativa y de ruta {args.ruta} exitosa — {longitud_m:.0f} m, "
            f"clareo mínimo {clareo_m:.1f} m, altitud relativa {args.altitude:.0f} m"
        )
        return

    run_flight(
        connection_string=args.connection,
        target_altitude=args.altitude,
        weight_kg=args.weight,
        nombre_ruta=args.ruta,
    )


if __name__ == "__main__":
    main()
