# Migración a hardware real (dron + cámara)

Cómo pasar del entorno simulado (SITL + cámara sintética) a un dron físico.
**El frontend no cambia** — toda la diferencia vive en el backend y en las
cadenas de conexión. El único cambio en `drones-frontend` es el `.env` si la
API se mueve de host.

## 1. Enlace MAVLink (reemplaza SITL + MAVProxy)

En simulación, el backend recibe telemetría en `udp:127.0.0.1:14550` vía
MAVProxy. Con hardware real, DroneKit habla directo con el autopiloto — se
elimina SITL **y** MAVProxy del stack.

| Escenario | `connection_string` para `POST /drone/connect` |
|---|---|
| SITL (actual) | `127.0.0.1:14550` |
| Telemetría por radio (3DR/SiK) | `/dev/ttyUSB0` — añadir `baud: 57600` si el firmware lo requiere |
| Companion computer (RPi/Jetson, UART) | `/dev/serial0` o `/dev/ttyAMA0` (baud 921600/57600 según FC) |
| Enlace UDP (GCS remoto → backend) | `udpin:0.0.0.0:14550` o `udp:127.0.0.1:14550` según dirección |
| TCP (p.ej. FC expone 5760) | `tcp:IP_DEL_AUTOPILOTO:5760` |

Notas:

- Permisos serial: el usuario del backend debe pertenecer al grupo `dialout`
  (`sudo usermod -aG dialout $USER`, re-login).
- La cadena exacta usa la sintaxis de `pymavlink.mavutil.mavlink_connection`
  (misma que DroneKit acepta).
- En `scripts/drone_backend.py` el flag equivalente es `--connection`
  (default `127.0.0.1:14550`).

## 2. Cámara real (reemplaza `--source synthetic`)

El pipeline es idéntico: frames JPEG → `POST /api/v1/video/frame` → MJPEG en
`/video/live` + pipeline de visión. Solo cambia `--source`:

```bash
cd drones-backend
export DRONE_API_TOKEN=<jwt_admin>

# Webcam UVC local (/dev/video0)
venv/bin/python scripts/run_camera_stream.py --source 0 --fps 15

# Archivo/RTSP que OpenCV pueda abrir
venv/bin/python scripts/run_camera_stream.py --source /ruta/video.mp4
venv/bin/python scripts/run_camera_stream.py --source "rtsp://IP_CAM/stream"

# Reenvío a un servidor RTSP externo (ej. MediaMTX) vía ffmpeg
venv/bin/python scripts/run_camera_stream.py --source 0 \
    --rtsp-url rtsp://IP_MEDIAMTX:8554/dron
```

- La resolución real se anuncia al backend por los params `width`/`height`
  que el script ya envía por frame.
- Grabación continua igual que en simulación: `scripts/record_stream.py
  --source http://127.0.0.1:8000/api/v1/video/live --segment-seconds 10`.

## 3. Detecciones reales

`/detections/ingest` sigue siendo el punto de entrada — pero en hardware real
lo llama el pipeline de visión del backend (`app/vision/`), no un curl de
demo. No hay nada que cambiar en frontend.

## 4. Geocercas y HOME

- Redibujar las geocercas operativas sobre la zona real de vuelo (la UI las
  persiste vía `POST /geofences`).
- La base de carga reporta el HOME real vía `GET /drone/charging-base`;
  en físico depende del firmware del helipuerto (RNF06).

## 5. Checklist de migración

- [ ] Backend `.env` con `DATABASE_URL`/`SECRET_KEY` de producción.
- [ ] `connection_string` del dron físico (tabla arriba) — probar primero
      con `POST /drone/connect` desde Swagger.
- [ ] Permisos `dialout` para el puerto serie.
- [ ] Failsafe habilitado antes del primer vuelo:
      `POST /drone/failsafe?enabled=true`.
- [ ] Cámara real publicando frames (`run_camera_stream.py --source <real>`).
- [ ] Geocercas reales dibujadas y activas.
- [ ] Frontend `.env` (`VITE_API_URL`/`VITE_WS_URL`) apuntando al host real —
      único archivo del frontend a tocar.
