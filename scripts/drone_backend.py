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
# Coordenadas WGS84 obtenidas directamente de las teselas satelitales de
# MAVProxy (UAQ Campus Juriquilla), independientes del recorte de imagen:
#   - Campus acotado al oeste de Carretera a Juriquilla, al sur de Blvd. Villas
#     del Mesón y al este de la vialidad divisoria con la UNAM.
#   - Zonas azules expresadas como (lat, lon, radio_m).
EARTH_RADIUS_M = 6378137.0

HOME_COORDS = (20.704280, -100.443580)    # Facultad de Informática (despegue SITL)
BASE_1_COORDS = (20.701383, -100.441494)  # Base 1 (rojo, acceso sureste del campus)
BASE_2_COORDS = (20.705145, -100.444093)  # Base 2 (rojo, estacionamiento noroeste)

# Zonas de interferencia (azul): (lat, lon, radio_m)
ZONAS_INTERFERENCIA = [
    (20.703971, -100.444044, 19.0),       # edificio curvo noroeste
    (20.703524, -100.443300, 22.0),       # cancha techada central (marca X)
    (20.702825, -100.444314, 35.0),       # límite oeste junto a nave blanca (marca X)
    (20.702645, -100.443300, 34.0),       # edificio de tejado rojo central
    (20.701567, -100.442614, 33.0),       # zona sur "?"
]

# 1) Traslado inicial HOME → Base 1 reconociendo explanadas interiores del este
#    sin acercarse a Carretera a Juriquilla.
RUTA_TRASLADO = [
    (20.704086, -100.443178),
    (20.703742, -100.442974),
    (20.703169, -100.442830),
    (20.702729, -100.442544),
    (20.702175, -100.442258),
    (20.701640, -100.441911),
]

# 2) Barrido estratégico Base 1 → Base 2: carriles serpenteantes S→N dentro del
#    campus evitando todas las zonas azules. Un 3er valor indica segundos de hover.
RUTA_BARRIDO: list[tuple[float, float] | tuple[float, float, float]] = [
    (20.701640, -100.441931, 2),          # edificios del sur
    (20.701984, -100.442135),             # rodeo noreste de zona "?"
    (20.701984, -100.443096, 2),          # barrido sur (arriba de zona "?")
    (20.701984, -100.443974),             # límite suroeste dentro del campus
    (20.702194, -100.443974),             # cambio de carril sur-medio
    (20.702194, -100.442708),             # barrido O→E al sur de tejados rojos
    (20.702423, -100.442340, 2),          # explanada sur Biblioteca
    (20.702882, -100.442544),             # costado interior de Biblioteca
    (20.703169, -100.442830),             # corredor central entre zonas azules
    (20.703169, -100.443791, 3),          # explanada nave blanca / cancha (lejos de X oeste)
    (20.703589, -100.443688),             # cancha de futbol
    (20.703952, -100.443586),             # corredor norte de canchas
    (20.703933, -100.443035, 2),          # ala este interior (adentro de la reja)
    (20.704296, -100.443178),             # frente a Facultad de Informática
    (20.704380, -100.443811, 3),          # plaza circular / fuente de Informática
    (20.704698, -100.443361, 2),          # edificio norte (BN)
    (20.704965, -100.443484),             # estacionamiento norte (este)
    (20.704965, -100.443893, 2),          # estacionamiento norte (centro)
]

# 3) Regreso Base 2 → Base 1 por el corredor interior este (sin salir a la calle).
RUTA_REGRESO = [
    (20.704908, -100.443566),
    (20.704411, -100.443239),
    (20.703723, -100.442974),
    (20.702901, -100.442544),
    (20.702098, -100.442176),
    (20.701601, -100.441849),
]

ALT_BASE_M = 6.0                  # altura de "acoplamiento" sobre cada base
VEL_TRANSITO = 8.0                # m/s en regreso entre bases
VEL_BARRIDO = 6.0                 # m/s durante el reconocimiento
DIST_LLEGADA_M = 4.0
TOL_ALT_M = 1.5
TIMEOUT_TRAMO_S = 180
REINTENTO_DESTINO_S = 5.0
MAX_HEARTBEAT_S = 5.0


def _coords_a_metros(punto: tuple[float, float]) -> tuple[float, float]:
    """Proyecta (lat, lon) a metros locales (este, norte) respecto a HOME_COORDS."""
    lat, lon = punto
    ref_lat, ref_lon = HOME_COORDS
    este = math.radians(lon - ref_lon) * EARTH_RADIUS_M * math.cos(math.radians(ref_lat))
    norte = math.radians(lat - ref_lat) * EARTH_RADIUS_M
    return este, norte


def _dist_segmento_m(
    a: tuple[float, float],
    b: tuple[float, float],
    p: tuple[float, float],
) -> float:
    ax, ay = _coords_a_metros(a)
    bx, by = _coords_a_metros(b)
    px, py = _coords_a_metros(p)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def validar_ruta(margen_m: float = 8.0) -> tuple[float, float]:
    """Verifica en metros reales que ningún tramo se acerque a zonas de interferencia.

    Devuelve (clareo mínimo en m, longitud total de la ruta en m).
    """
    ruta: list[tuple[float, float]] = [
        HOME_COORDS,
        *RUTA_TRASLADO,
        BASE_1_COORDS,
        *[(p[0], p[1]) for p in RUTA_BARRIDO],
        BASE_2_COORDS,
        *RUTA_REGRESO,
        BASE_1_COORDS,
    ]
    clareo_min = math.inf
    distancia = 0.0
    for i in range(len(ruta) - 1):
        ax, ay = _coords_a_metros(ruta[i])
        bx, by = _coords_a_metros(ruta[i + 1])
        distancia += math.hypot(bx - ax, by - ay)
        for zlat, zlon, zradio_m in ZONAS_INTERFERENCIA:
            clareo = _dist_segmento_m(ruta[i], ruta[i + 1], (zlat, zlon)) - zradio_m
            clareo_min = min(clareo_min, clareo)
            if clareo < margen_m:
                raise ValueError(
                    f"El tramo {ruta[i]}→{ruta[i + 1]} pasa a {clareo:.1f} m "
                    f"de la zona de interferencia ({zlat}, {zlon})"
                )
    return clareo_min, distancia


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
    target_altitude: float = 15.0,
    weight_kg: float = 2.5,
) -> None:
    """Patrullaje: Base 1 → barrido evitando interferencias → Base 2 → Base 1."""
    validate_flight_plan(altitude_m=target_altitude, weight_kg=weight_kg)
    clareo_m, longitud_m = validar_ruta()
    print(f"Ruta validada: {longitud_m:.0f} m, clareo mínimo a interferencias {clareo_m:.1f} m")

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
        for i, punto in enumerate(RUTA_BARRIDO, 1):
            volar_a(vehicle, (punto[0], punto[1]), target_altitude, VEL_BARRIDO, f"tramo {i}/{len(RUTA_BARRIDO)}")
            if len(punto) > 2:
                print(f"    inspeccionando zona {punto[2]:.0f} s...")
                time.sleep(punto[2])
        volar_a(vehicle, BASE_2_COORDS, target_altitude, VEL_BARRIDO, "Base 2")

        print("3/4 Acoplamiento simulado en Base 2")
        volar_a(vehicle, BASE_2_COORDS, ALT_BASE_M, VEL_BARRIDO, "descenso a Base 2")
        time.sleep(4)
        volar_a(vehicle, BASE_2_COORDS, target_altitude, VEL_BARRIDO, "ascenso desde Base 2")

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
    parser.add_argument("--altitude", type=float, default=15.0)
    parser.add_argument("--weight", type=float, default=2.5)
    parser.add_argument("--dry-run", action="store_true", help="Solo valida normativa y ruta sin conectar al dron")
    args = parser.parse_args()

    if args.dry_run:
        validate_flight_plan(altitude_m=args.altitude, weight_kg=args.weight)
        clareo_m, longitud_m = validar_ruta()
        print(f"Validación normativa y de ruta exitosa — {longitud_m:.0f} m, clareo mínimo {clareo_m:.0f} m")
        return

    run_flight(connection_string=args.connection, target_altitude=args.altitude, weight_kg=args.weight)


if __name__ == "__main__":
    main()
