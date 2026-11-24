"""Cámara simulada que sigue al dron en tiempo real sobre mapa real.

Publica frames JPEG a /api/v1/video/frame con tiles de mapa reales (los mismos
servicios XYZ que usa el mapa de MAVProxy: satélite ESRI por defecto, OSM con
--tiles osm) centrados en la posición GPS del dron según la telemetría del
backend. Encima dibuja retícula, waypoints, geocercas, HOME y el rastro del
vuelo — equivalente a la ventana de mapa de MAVProxy dentro del stream.

Uso:
    venv/bin/python scripts/run_telemetry_camera.py --token <JWT> [--fps 10]
    venv/bin/python scripts/run_telemetry_camera.py --token <JWT> --tiles osm
"""

import argparse
import hashlib
import math
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import cv2
import httpx
import numpy as np

HOME = (20.70428, -100.44358)
M_LAT = 111_320.0
M_LON = 111_320.0 * math.cos(math.radians(HOME[0]))

TILE_SOURCES = {
    # Satélite ESRI — mismo aspecto que el mapa de MAVProxy en modo satélite
    "sat": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    # OpenStreetMap estándar
    "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
}
TILE_CACHE = Path("/tmp/uav_tiles")
TILE_PX = 256

WHITE = (235, 235, 235)
CYAN = (220, 200, 80)
GREEN_HOME = (140, 255, 140)
ORANGE_WP = (80, 220, 255)
TEAL_GEOFENCE = (60, 200, 220)
TRAIL = (0, 255, 255)
DRONE_RED = (60, 60, 235)
RED_NOFLY = (80, 80, 230)
PURPLE_BASE = (200, 110, 220)


def latlon_to_world(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Coordenada mundial en píxeles Web-Mercator para un zoom dado."""
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * TILE_PX * n
    siny = math.sin(math.radians(max(-85.0, min(85.0, lat))))
    y = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * TILE_PX * n
    return x, y


def meters_per_px(lat: float, zoom: int) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)


def zoom_for_fov(fov_m: float, lat: float, width: int) -> int:
    """Zoom cuya resolución se aproxime al ancho en metros deseado."""
    mpp_wanted = fov_m / width
    z = math.log2(156543.03392 * math.cos(math.radians(lat)) / mpp_wanted)
    return min(19, max(13, int(round(z))))


def _load_tile(client, url_tpl: str, source: str, zoom: int, tx: int, ty: int) -> np.ndarray | None:
    path = TILE_CACHE / source / str(zoom) / str(tx) / f"{ty}.png"
    if path.exists():
        data = path.read_bytes()
    else:
        try:
            r = client.get(url_tpl.format(z=zoom, x=tx, y=ty), timeout=4.0)
            if r.status_code != 200 or len(r.content) < 500:
                return None
            data = r.content
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except Exception:
            return None
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return img


def fetch_map_area(client, source: str, cx: float, cy: float, w: int, h: int,
                   zoom: int) -> tuple[np.ndarray, int]:
    """Compone el área wxh centrada en el pixel mundial (cx, cy) con tiles."""
    url_tpl = TILE_SOURCES[source]
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    x0, y0 = cx - w / 2, cy - h / 2
    n = 2 ** zoom
    ok = 0
    for tx in range(max(0, int(x0 // TILE_PX)), min(n - 1, int((x0 + w) // TILE_PX)) + 1):
        for ty in range(max(0, int(y0 // TILE_PX)), min(n - 1, int((y0 + h) // TILE_PX)) + 1):
            tile = _load_tile(client, url_tpl, source, zoom, tx, ty)
            if tile is None:
                continue
            ok += 1
            px, py = int(tx * TILE_PX - x0), int(ty * TILE_PX - y0)
            # recorte por bordes del canvas
            sx0, sy0 = max(0, -px), max(0, -py)
            ex = min(w, px + TILE_PX)
            ey = min(h, py + TILE_PX)
            if ex <= px + sx0 or ey <= py + sy0:
                continue
            canvas[py + sy0:ey, px + sx0:ex] = tile[sy0:ey - py, sx0:ex - px]
    return canvas, ok


def wpx(lat: float, lon: float, cx: float, cy: float, zoom: int, w: int, h: int):
    """lat/lon → píxel del canvas."""
    x, y = latlon_to_world(lat, lon, zoom)
    return int(x - (cx - w / 2)), int(y - (cy - h / 2))


def draw_world(frame, dx, dy, ppm, w, h):
    """Fallback sin red: retícula urbana procedural (caché vacío)."""
    BLOCK, ROAD_W, m = 90.0, 8.0, 8.0
    import random
    ROAD, GREEN, BG = (66, 66, 72), (36, 82, 46), (28, 60, 34)
    frame[:, :] = BG
    half_m = max(w, h) / ppm / 2 + BLOCK

    def mp(wx, wy):
        return int(w / 2 + (wx - dx) * ppm), int(h / 2 - (wy - dy) * ppm)

    for ix in range(int((dx - half_m) // BLOCK), int((dx + half_m) // BLOCK) + 2):
        cv2.line(frame, mp(ix * BLOCK, dy - half_m), mp(ix * BLOCK, dy + half_m),
                 ROAD, max(2, int(ROAD_W * ppm)))
    for iy in range(int((dy - half_m) // BLOCK), int((dy + half_m) // BLOCK) + 2):
        cv2.line(frame, mp(dx - half_m, iy * BLOCK), mp(dx + half_m, iy * BLOCK),
                 ROAD, max(2, int(ROAD_W * ppm)))
    for ix in range(int((dx - half_m) // BLOCK), int((dx + half_m) // BLOCK) + 1):
        for iy in range(int((dy - half_m) // BLOCK), int((dy + half_m) // BLOCK) + 1):
            rng = random.Random(ix * 73856093 ^ iy * 19349663)
            bx, by, bw = ix * BLOCK + m, iy * BLOCK + m, BLOCK - 2 * m
            if rng.random() < 0.22:
                cv2.rectangle(frame, mp(bx, by + bw), mp(bx + bw, by), GREEN, -1)
            else:
                for _ in range(rng.randint(1, 2)):
                    ew, eh = rng.uniform(0.3, 0.6) * bw, rng.uniform(0.3, 0.6) * bw
                    ex, ey = bx + rng.uniform(0.05, 0.4) * bw, by + rng.uniform(0.05, 0.4) * bw
                    g = rng.randint(88, 128)
                    cv2.rectangle(frame, mp(ex, ey + eh), mp(ex + ew, ey), (g - 8, g - 4, g + 8), -1)


def render(client, source: str, tel: dict, mission: dict | None, geofences: list,
           exclusion: list, bases: list, trail: deque, w: int, h: int) -> np.ndarray:
    lat = tel.get("latitud") or HOME[0]
    lon = tel.get("longitud") or HOME[1]
    alt = max(0.0, tel.get("altitud_metros") or 0.0)
    hdg = tel.get("rumbo_grados") or 0.0

    # Encuadre tipo MAVProxy: la vista cubre dron + HOME + waypoints activos
    # (bbox en metros relativo a HOME, con 25% de margen, mín 140 m).
    wps_all = sorted((mission or {}).get("waypoints") or [],
                     key=lambda x: x.get("orden_waypoint", 0))
    pts_m = [((lon - HOME[1]) * M_LON, (lat - HOME[0]) * M_LAT), (0.0, 0.0)]
    pts_m += [((wp.get("longitud", HOME[1]) - HOME[1]) * M_LON,
               (wp.get("latitud", HOME[0]) - HOME[0]) * M_LAT) for wp in wps_all]
    # El encuadre también cubre zonas de exclusión y bases, para que el
    # mapa muestre el contexto operativo completo aunque no haya misión.
    for z in exclusion:
        if z.get("activa", True):
            pts_m += [
                ((z["lon_min"] - HOME[1]) * M_LON, (z["lat_min"] - HOME[0]) * M_LAT),
                ((z["lon_max"] - HOME[1]) * M_LON, (z["lat_max"] - HOME[0]) * M_LAT),
            ]
    for b in bases:
        c = b.get("coords")
        if c:
            pts_m.append(((c[1] - HOME[1]) * M_LON, (c[0] - HOME[0]) * M_LAT))
    xs = [p[0] for p in pts_m]
    ys = [p[1] for p in pts_m]
    cx_m, cy_m = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    # La vista es w:h (no cuadrada): si la extensión vertical domina el bbox,
    # hay que ampliar el span o el contenido queda recortado arriba/abajo.
    span = max(max(xs) - min(xs),
               (max(ys) - min(ys)) * (w / h),
               140.0) * 1.25

    zoom = zoom_for_fov(span, lat, w)
    center_lat = HOME[0] + cy_m / M_LAT
    center_lon = HOME[1] + cx_m / M_LON
    cx, cy = latlon_to_world(center_lat, center_lon, zoom)
    frame, tiles_ok = fetch_map_area(client, source, cx, cy, w, h, zoom)
    mpp = meters_per_px(lat, zoom)

    if tiles_ok == 0:  # sin red → mundo procedural
        draw_world(frame, cx_m, cy_m, w / span, w, h)
        px_at = lambda la, lo: (
            int(w / 2 + ((lo - HOME[1]) * M_LON - cx_m) * (w / span)),
            int(h / 2 - ((la - HOME[0]) * M_LAT - cy_m) * (w / span)),
        )
        scale_mpp = span / w
    else:
        px_at = lambda la, lo: wpx(la, lo, cx, cy, zoom, w, h)
        scale_mpp = mpp

    # Rastro del vuelo
    if len(trail) > 1:
        pts = np.array([px_at(la, lo) for la, lo in trail], dtype=np.int32)
        cv2.polylines(frame, [pts], False, TRAIL, 2, cv2.LINE_AA)

    # Geocercas activas
    for g in geofences:
        if not g.get("activa", True):
            continue
        if g.get("centro_lat") and g.get("radio_metros"):
            cp = px_at(g["centro_lat"], g["centro_lon"])
            cv2.circle(frame, cp, max(2, int(g["radio_metros"] / scale_mpp)),
                       TEAL_GEOFENCE, 1, cv2.LINE_AA)
        poly = g.get("poligono")
        if poly and len(poly) >= 3:
            pts = np.array([px_at(v.get("latitud", v.get("lat", 0)),
                                  v.get("longitud", v.get("lon", 0))) for v in poly],
                           dtype=np.int32)
            cv2.polylines(frame, [pts], True, TEAL_GEOFENCE, 1, cv2.LINE_AA)

    # Zonas de exclusión (no sobrevuelo): rectángulos rojos punteados
    def _dashed_seg(a, b, dash=8):
        dist = math.hypot(b[0] - a[0], b[1] - a[1])
        steps = max(1, int(dist // dash))
        for s in range(0, steps, 2):
            t0, t1 = s / steps, min(1.0, (s + 1) / steps)
            cv2.line(frame,
                     (int(a[0] + (b[0]-a[0])*t0), int(a[1] + (b[1]-a[1])*t0)),
                     (int(a[0] + (b[0]-a[0])*t1), int(a[1] + (b[1]-a[1])*t1)),
                     RED_NOFLY, 1, cv2.LINE_AA)

    for z in exclusion:
        if not z.get("activa", True):
            continue
        tl = px_at(z["lat_max"], z["lon_min"])  # esquina sup. izq (norte-oeste)
        br = px_at(z["lat_min"], z["lon_max"])  # esquina inf. der (sur-este)
        tr, bl = (br[0], tl[1]), (tl[0], br[1])
        _dashed_seg(tl, tr); _dashed_seg(tr, br)
        _dashed_seg(br, bl); _dashed_seg(bl, tl)
        cv2.putText(frame, f"X {z.get('nombre','')}",
                    (tl[0] + 4, tl[1] - 5), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, RED_NOFLY, 1, cv2.LINE_AA)

    # Bases de patrullaje (B1/B2; HOME se dibuja aparte)
    for base in bases:
        if base.get("id") == "home":
            continue
        bp = px_at(base["coords"][0], base["coords"][1])
        if 0 <= bp[0] < w and 0 <= bp[1] < h:
            cv2.drawMarker(frame, bp, PURPLE_BASE, cv2.MARKER_DIAMOND, 16, 2)
            cv2.putText(frame, base.get("label", "B?"), (bp[0] + 10, bp[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, PURPLE_BASE, 1, cv2.LINE_AA)

    # Ruta planificada de la misión: HOME → W1 → W2 → … → Wn → HOME
    # (línea punteada estilo MAVProxy) + marcadores numerados.
    wps = sorted((mission or {}).get("waypoints") or [],
                 key=lambda w: w.get("orden_waypoint", 0))
    if wps:
        route_pts = [px_at(*HOME)] + [px_at(w.get("latitud", 0), w.get("longitud", 0))
                                      for w in wps] + [px_at(*HOME)]
        for a, b in zip(route_pts, route_pts[1:]):
            # segmento punteado manual (cv2 no tiene dash nativo)
            dist = math.hypot(b[0] - a[0], b[1] - a[1])
            steps = max(1, int(dist // 14))
            for s in range(0, steps, 2):
                t0, t1 = s / steps, min(1, (s + 1) / steps)
                p0 = (int(a[0] + (b[0] - a[0]) * t0), int(a[1] + (b[1] - a[1]) * t0))
                p1 = (int(a[0] + (b[0] - a[0]) * t1), int(a[1] + (b[1] - a[1]) * t1))
                cv2.line(frame, p0, p1, ORANGE_WP, 2, cv2.LINE_AA)
        for i, wp in enumerate(wps):
            pp = px_at(wp.get("latitud", 0), wp.get("longitud", 0))
            cv2.drawMarker(frame, pp, ORANGE_WP, cv2.MARKER_TILTED_CROSS, 14, 2)
            cv2.putText(frame, f"W{i+1}", (pp[0] + 8, pp[1] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, ORANGE_WP, 1, cv2.LINE_AA)

    # HOME; si queda fuera de la vista, indicador al borde
    hp = px_at(*HOME)
    if 0 <= hp[0] < w and 0 <= hp[1] < h:
        cv2.drawMarker(frame, hp, GREEN_HOME, cv2.MARKER_SQUARE, 16, 2)
        cv2.putText(frame, "HOME", (hp[0] + 10, hp[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, GREEN_HOME, 1, cv2.LINE_AA)
    else:
        ang = math.atan2(-(hp[1] - h // 2), hp[0] - w // 2)
        ex = w // 2 + int(math.cos(ang) * (w // 2 - 50))
        ey = h // 2 - int(math.sin(ang) * (h // 2 - 60))
        cv2.putText(frame, "HOME >", (ex - 30, ey),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, GREEN_HOME, 1, cv2.LINE_AA)

    # Icono del dron: flecha estilo MAVProxy orientada al rumbo (0°=N=arriba)
    # + retícula de cámara. Si el dron sale del encuadre, marcador al borde
    # apuntando hacia su dirección (como el indicador de HOME).
    cxp, cyp = px_at(lat, lon)
    rad = math.radians(hdg - 90)
    if 0 <= cxp < w and 0 <= cyp < h:
        cv2.circle(frame, (cxp, cyp), 55, WHITE, 1, cv2.LINE_AA)
        cv2.line(frame, (cxp - 20, cyp), (cxp + 20, cyp), WHITE, 1, cv2.LINE_AA)
        cv2.line(frame, (cxp, cyp - 20), (cxp, cyp + 20), WHITE, 1, cv2.LINE_AA)
        cv2.line(frame, (cxp, cyp),
                 (cxp + int(45 * math.cos(rad)), cyp + int(45 * math.sin(rad))),
                 CYAN, 2, cv2.LINE_AA)
        tip = (cxp + int(22 * math.cos(rad)), cyp + int(22 * math.sin(rad)))
        rear_l = (cxp + int(15 * math.cos(rad + 2.55)), cyp + int(15 * math.sin(rad + 2.55)))
        rear_r = (cxp + int(15 * math.cos(rad - 2.55)), cyp + int(15 * math.sin(rad - 2.55)))
        tri = np.array([tip, rear_l, rear_r], dtype=np.int32)
        cv2.fillConvexPoly(frame, tri, DRONE_RED, cv2.LINE_AA)
        cv2.polylines(frame, [tri], True, WHITE, 1, cv2.LINE_AA)
        cv2.putText(frame, "DRON", (cxp + 26, cyp + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, DRONE_RED, 1, cv2.LINE_AA)
    else:
        ex = max(30, min(w - 30, cxp))
        ey = max(30, min(h - 30, cyp))
        ang = math.atan2(cyp - ey, cxp - ex)
        tip = (ex + int(18 * math.cos(ang)), ey + int(18 * math.sin(ang)))
        rear_l = (ex + int(12 * math.cos(ang + 2.6)), ey + int(12 * math.sin(ang + 2.6)))
        rear_r = (ex + int(12 * math.cos(ang - 2.6)), ey + int(12 * math.sin(ang - 2.6)))
        tri = np.array([tip, rear_l, rear_r], dtype=np.int32)
        cv2.fillConvexPoly(frame, tri, DRONE_RED, cv2.LINE_AA)
        cv2.polylines(frame, [tri], True, WHITE, 1, cv2.LINE_AA)
        cv2.putText(frame, "DRON", (ex - 20, ey - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, DRONE_RED, 1, cv2.LINE_AA)

    # HUD
    mode = tel.get("modo_vuelo") or "?"
    armed = bool(tel.get("armado"))
    spd = tel.get("velocidad_tierra_ms") or 0.0
    bat = tel.get("bateria_porcentaje") or 0
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    cv2.rectangle(frame, (0, 0), (w, 30), (15, 15, 15), -1)
    cv2.putText(frame, f"UAV SIM CAM | {mode} {'ARMED' if armed else 'DISARMED'} | BAT {bat:.0f}%",
                (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1, cv2.LINE_AA)
    cv2.putText(frame, ts, (w - 235, 20), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, WHITE, 1, cv2.LINE_AA)
    cv2.rectangle(frame, (0, h - 30), (w, h), (15, 15, 15), -1)
    mtxt = f"M{mission['id']} {mission['estado']}" if mission else "SIN MISION"
    cv2.putText(frame,
                f"{mtxt} | ALT {alt:.1f}m | SPD {spd:.1f}m/s | HDG {hdg:.0f} | "
                f"{lat:.5f}, {lon:.5f}",
                (10, h - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1, cv2.LINE_AA)
    return frame


def fetch_json(client, base, path, token):
    try:
        r = client.get(f"{base}{path}", headers={"Authorization": f"Bearer {token}"},
                       timeout=3.0)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def main() -> None:
    p = argparse.ArgumentParser(description="Cámara simulada sobre mapa real sincronizada con telemetría")
    p.add_argument("--backend-url", default="http://127.0.0.1:8000")
    p.add_argument("--token", default=os.getenv("DRONE_API_TOKEN", ""))
    p.add_argument("--fps", type=float, default=5.0,
                   help="frames publicados por segundo (default 5; sube solo si el stream se ve entrecortado)")
    p.add_argument("--quality", type=int, default=82)
    p.add_argument("--width", type=int, default=800)
    p.add_argument("--height", type=int, default=600)
    p.add_argument("--tiles", choices=list(TILE_SOURCES), default="sat",
                   help="sat = satélite ESRI (estilo MAVProxy), osm = callejero")
    args = p.parse_args()
    if not args.token:
        raise SystemExit("Se requiere --token o DRONE_API_TOKEN")

    api = args.backend_url.rstrip("/") + "/api/v1"
    interval = 1.0 / max(0.5, args.fps)
    # Cadencias desacopladas del fps: la telemetría solo refresca el overlay
    # (~1 Hz basta) y los metadatos de ruta/geocercas ~5 s. Sin esto el bucle
    # descargaba /telemetry/current a 10 req/s por frame publicado.
    TELEMETRY_REFRESH_S = 1.0
    META_REFRESH_S = 5.0
    sent, tick = 0, 0
    mission, geofences = None, []
    exclusion, bases = [], []
    trail = deque(maxlen=600)
    last_trail = None
    tel = {}
    last_tel_fetch = 0.0
    last_meta_fetch = 0.0
    last_frame_hash = None
    last_frame_sent = 0.0
    # Reenvío de heartbeat aunque el frame no cambie: cubre reinicios del
    # backend (su caché de último frame queda vacía tras un restart).
    FRAME_HEARTBEAT_S = 10.0

    headers = {
        "Authorization": f"Bearer {args.token}",
        "User-Agent": "UAQ-drone-sim/1.0 (telemetry camera)",
    }
    with httpx.Client(timeout=5.0, headers=headers) as client:
        while True:
            tick += 1
            now = time.monotonic()
            if now - last_tel_fetch >= TELEMETRY_REFRESH_S:
                fetched = fetch_json(client, api, "/telemetry/current", args.token)
                if fetched is not None:
                    tel = fetched
                last_tel_fetch = now
            if now - last_meta_fetch >= META_REFRESH_S:
                last_meta_fetch = now
                ms = fetch_json(client, api, "/missions/", args.token)
                if ms is not None:  # fetch fallido → conserva la anterior (evita parpadeo)
                    # Solo misiones vivas: la lista viene desc por id, así que
                    # la primera PROGRAMADA es la más reciente. FALLIDA/CANCELADA
                    # no dibujan ruta (estado en tarjetas de Rutas, no aquí).
                    mission = next(
                        (m for m in ms if m.get("estado") in ("EN_CURSO", "RECUPERACION")),
                        next((m for m in ms if m.get("estado") == "PROGRAMADA"), None),
                    )
                geofences = fetch_json(client, api, "/geofences/", args.token) or geofences
                exclusion = fetch_json(client, api, "/exclusion-zones/", args.token) or exclusion
                presets = fetch_json(client, api, "/missions/presets", args.token) or []
                if presets:
                    bases = presets[0].get("bases") or bases

            # Punto del rastro cuando el dron se mueve
            la, lo = tel.get("latitud"), tel.get("longitud")
            if tel.get("armado") and la and lo:
                if not last_trail or math.hypot(
                        (lo - last_trail[1]) * M_LON, (la - last_trail[0]) * M_LAT) > 2.0:
                    trail.append((la, lo))
                    last_trail = (la, lo)

            frame = render(client, args.tiles, tel, mission, geofences, exclusion,
                           bases, trail, args.width, args.height)
            ok, enc = cv2.imencode(".jpg", frame,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), args.quality])
            if ok:
                # Dedup: si el frame renderizado es idéntico al ya publicado
                # (dron quieto, telemetría sin cambios) no se vuelve a subir —
                # el backend sirve su caché del último frame a /snapshot y al
                # stream MJPEG. Esto elimina ~5 uploads/s en reposo.
                jpeg_bytes = enc.tobytes()
                frame_hash = hashlib.md5(jpeg_bytes).digest()
                if frame_hash != last_frame_hash or now - last_frame_sent >= FRAME_HEARTBEAT_S:
                    try:
                        client.post(f"{api}/video/frame",
                                    params={"width": args.width, "height": args.height},
                                    files={"file": ("frame.jpg", jpeg_bytes, "image/jpeg")},
                                    ).raise_for_status()
                        sent += 1
                        last_frame_hash = frame_hash
                        last_frame_sent = now
                    except Exception:
                        time.sleep(1.0)
            if tick % 300 == 0:
                print(f"[cam] {sent} frames publicados", flush=True)
            time.sleep(interval)


if __name__ == "__main__":
    main()
