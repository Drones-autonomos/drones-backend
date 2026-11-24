"""Rutas de patrullaje preprogramadas del campus UAQ Juriquilla.

Fuente única de verdad compartida por:
- ``scripts/drone_backend.py`` (controlador de vuelo DroneKit/SITL), que
  importa las coordenadas y ``validar_ruta()`` desde este módulo.
- ``GET /api/v1/missions/presets`` (FastAPI) vía ``get_patrol_presets()``.
- El fallback offline del frontend en
  ``drones-frontend/src/pages/Admin/presetRoutes.js`` — si se modifican las
  coordenadas hay que sincronizar ese archivo manualmente.

Coordenadas WGS84 obtenidas de las teselas satelitales de MAVProxy:
  - Campus acotado al oeste de Carretera a Juriquilla, al sur de Blvd. Villas
    del Mesón y al este de la vialidad divisoria con la UNAM.
  - Zonas azules (interferencia) expresadas como (lat, lon, radio_m).
"""

import math

EARTH_RADIUS_M = 6378137.0

HOME_COORDS = (20.704280, -100.443580)  # Facultad de Informática (despegue SITL)
BASE_1_COORDS = (20.701383, -100.441494)  # Base 1 (rojo, acceso sureste del campus)
BASE_2_COORDS = (20.705145, -100.444093)  # Base 2 (rojo, estacionamiento noroeste)

# Zonas de interferencia (azul): (lat, lon, radio_m)
ZONAS_INTERFERENCIA = [
    (20.703971, -100.444044, 19.0),  # edificio curvo noroeste
    (20.703524, -100.443300, 22.0),  # cancha techada central (marca X)
    (20.702825, -100.444314, 35.0),  # límite oeste junto a nave blanca (marca X)
    (20.702645, -100.443300, 34.0),  # edificio de tejado rojo central
    (20.701567, -100.442614, 33.0),  # zona sur "?"
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
    (20.701640, -100.441931, 2),  # edificios del sur
    (20.701984, -100.442135),  # rodeo noreste de zona "?"
    (20.701984, -100.443096, 2),  # barrido sur (arriba de zona "?")
    (20.701984, -100.443974),  # límite suroeste dentro del campus
    (20.702194, -100.443974),  # cambio de carril sur-medio
    (20.702194, -100.442708),  # barrido O→E al sur de tejados rojos
    (20.702423, -100.442340, 2),  # explanada sur Biblioteca
    (20.702882, -100.442544),  # costado interior de Biblioteca
    (20.703169, -100.442830),  # corredor central entre zonas azules
    (20.703169, -100.443791, 3),  # explanada nave blanca / cancha (lejos de X oeste)
    (20.703589, -100.443688),  # cancha de futbol
    (20.703952, -100.443586),  # corredor norte de canchas
    (20.703933, -100.443035, 2),  # ala este interior (adentro de la reja)
    (20.704296, -100.443178),  # frente a Facultad de Informática
    (20.704380, -100.443811, 3),  # plaza circular / fuente de Informática
    (20.704698, -100.443361, 2),  # edificio norte (BN)
    (20.704965, -100.443484),  # estacionamiento norte (este)
    (20.704965, -100.443893, 2),  # estacionamiento norte (centro)
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

RUTAS_BARRIDO = {
    "clasica": RUTA_BARRIDO,
    "interior": [
        (20.701640, -100.441931, 2),
        (20.701950, -100.442100),
        (20.702400, -100.442340, 3),
        (20.702860, -100.442540),
        (20.703200, -100.442840, 3),
        (20.703740, -100.442974),
        (20.704086, -100.443178),
        (20.704380, -100.443811, 3),
        (20.704698, -100.443361, 2),
        (20.704965, -100.443484),
        (20.704965, -100.443893, 2),
    ],
    "canchas": [
        (20.701640, -100.441931),
        (20.702014, -100.442135),
        (20.702014, -100.443096, 3),
        (20.702014, -100.443974),
        (20.702224, -100.443974),
        (20.702224, -100.442708),
        (20.702423, -100.442340),
        (20.702882, -100.442544),
        (20.703200, -100.442840),
        (20.703200, -100.443740, 3),
        (20.703600, -100.443700, 3),
        (20.703990, -100.443580),
        (20.704380, -100.443811, 3),
        (20.704698, -100.443361),
        (20.704965, -100.443484),
        (20.704965, -100.443893, 2),
    ],
}
ALT_RECORRIDO_M = 30.0

# Metadatos para la API y el selector del frontend (ProgramarRuta.jsx).
RUTAS_METADATA = {
    "clasica": {
        "name": "Patrullaje Clásica",
        "description": (
            "Barrido completo S→N del campus: explanadas del este, biblioteca, "
            "corredor central, canchas, FIF y estacionamientos."
        ),
    },
    "interior": {
        "name": "Patrullaje Interior",
        "description": (
            "Corredor interior este y plaza norte: traslado corto, barrido por "
            "dentro de los edificios y regreso a Base 1."
        ),
    },
    "canchas": {
        "name": "Patrullaje Canchas",
        "description": (
            "Sector sur y canchas: rodeo de zonas de interferencia, cancha "
            "techada, campo de futbol y estacionamientos."
        ),
    },
}

# Bases fijas del circuito de patrullaje (marcadores del mapa del frontend).
PATROL_BASES = [
    {
        "id": "home",
        "label": "HOME",
        "tooltip": "Base principal · Facultad de Informática",
        "coords": [HOME_COORDS[0], HOME_COORDS[1]],
    },
    {
        "id": "base1",
        "label": "B1",
        "tooltip": "Base 1 · acceso sureste del campus",
        "coords": [BASE_1_COORDS[0], BASE_1_COORDS[1]],
    },
    {
        "id": "base2",
        "label": "B2 ⚡",
        "tooltip": "Base 2 · base de carga (estacionamiento noroeste)",
        "coords": [BASE_2_COORDS[0], BASE_2_COORDS[1]],
    },
]


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


def validar_ruta(margen_m: float = 8.0, *, nombre_ruta: str = "clasica") -> tuple[float, float]:
    """Verifica en metros reales que ningún tramo se acerque a zonas de interferencia.

    Devuelve (clareo mínimo en m, longitud total de la ruta en m).
    """
    if nombre_ruta not in RUTAS_BARRIDO:
        raise ValueError(f"Ruta desconocida: {nombre_ruta}. Opciones: {', '.join(RUTAS_BARRIDO)}")
    ruta: list[tuple[float, float]] = [
        HOME_COORDS,
        *RUTA_TRASLADO,
        BASE_1_COORDS,
        *[(p[0], p[1]) for p in RUTAS_BARRIDO[nombre_ruta]],
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


def _waypoint_dict(punto: tuple[float, ...]) -> dict:
    """Convierte un tuple (lat, lon[, hover_s]) al shape de la API."""
    wp = {"latitud": punto[0], "longitud": punto[1]}
    if len(punto) > 2:
        wp["hover_s"] = punto[2]
    return wp


def _ruta_completa(nombre_ruta: str) -> list[dict]:
    """Trayecto completo: traslado + Base 1 + barrido + Base 2 + regreso + Base 1."""
    secuencia = [
        *RUTA_TRASLADO,
        BASE_1_COORDS,
        *RUTAS_BARRIDO[nombre_ruta],
        BASE_2_COORDS,
        *RUTA_REGRESO,
        BASE_1_COORDS,
    ]
    return [_waypoint_dict(p) for p in secuencia]


def get_patrol_presets() -> list[dict]:
    """Payload de GET /missions/presets: las variantes de patrullaje validadas.

    Cada preset incluye los waypoints ordenados del trayecto completo
    (traslado → barrido → regreso a Base 1) como objetos
    ``{latitud, longitud, hover_s?}``, las bases fijas del circuito y HOME.
    """
    presets = []
    for nombre_ruta, meta in RUTAS_METADATA.items():
        clareo_m, longitud_m = validar_ruta(nombre_ruta=nombre_ruta)
        presets.append(
            {
                "id": nombre_ruta,
                "name": meta["name"],
                "description": meta["description"],
                "altitude_m": ALT_RECORRIDO_M,
                "waypoints": _ruta_completa(nombre_ruta),
                "route_length_m": round(longitud_m, 1),
                "clearance_m": round(clareo_m, 1),
                "bases": PATROL_BASES,
                "home": [HOME_COORDS[0], HOME_COORDS[1]],
            }
        )
    return presets
