# Corrida E2E guiada — AeroLuferan (Frontend ↔ Backend ↔ SITL)

Flujo de demostración punta a punta del sistema: login → misión → vuelo →
telemetría + video → detección → alerta → RTL → bitácora.

Prerrequisito: stack levantado con un solo comando desde `drones-backend/`:

```bash
./scripts/dev-stack.sh                 # DB + API + SITL + MAVProxy + Vite
./scripts/dev-stack.sh --bootstrap-admin   # además crea el admin inicial (interactivo)
```

> Si la base de datos ya tiene un administrador, omite `--bootstrap-admin`.
> Checklist equivalente a nivel API (curl) en `docs/DEMO_CHECKLIST.md`.

---

## 1. Login (administrador)

1. Abrir `http://localhost:5173`.
2. Seleccionar **Académico · Admin**, escribir el correo y contraseña del
   bootstrap (`python -m app.bootstrap_admin`).
3. `POST /auth/login` guarda el JWT en `localStorage["aeroluferan_session"]`;
   `GET /auth/me` hidrata el perfil y redirige a `/admin/en-vivo`.

**Verificación:** el badge de señal muestra **"Sin Señal"** (dron aún no
conectado) — esto es lo esperado, no un error.

## 2. Conectar el dron

1. Ir a **Rutas** (`/admin/rutas`).
2. Clic en el badge **"Sin Señal"** del encabezado → `POST /drone/connect`
   con `connection_string: "127.0.0.1:14550"` (el `udp:` de MAVProxy).
3. En ~2–5 s la telemetría empieza a llegar: el badge pasa a `NN%` verde,
   las tarjetas de En Vivo muestran batería/altitud/GPS reales.

**Fallback API:** `curl -X POST http://localhost:8000/api/v1/drone/connect \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"connection_string": "127.0.0.1:14550"}'`

## 3. Geocerca operativa (una sola vez)

Los waypoints de una misión deben caer **dentro de al menos una geocerca
activa** — el backend rechaza con 422 cualquier punto fuera de zona.

1. En `/admin/rutas` → **"Ajustar Perímetro"** → **"Dibujar Nueva Zona
   Rectangular"** → dos clics sobre el mapa cubriendo el campus.
2. Clasificarla como **Informativa** (las informativas son las que se
   persisten como geocercas operativas en el backend; solo ADMIN).

## 4. Programar la misión

1. **"Programar Nueva Ruta"** → escribir nombre (≥3 chars).
2. Clics en el mapa: **mínimo 2 waypoints, todos dentro de la geocerca**.
3. Ajustar altura operativa (30–200 m; el slider ya cumple el tope normativo).
4. Configurar despegue/aterrizaje/frecuencia y **"Programar vuelo"**
   → `POST /missions/` (201). La tarjeta aparece como **PROGRAMADA**.

> Si algún waypoint cae fuera de la geocerca, la UI muestra el `motivo`
> devuelto por `/geofences/validate-point` y no envía el POST.

## 5. Iniciar y monitorear

1. Seleccionar la tarjeta de la misión → **"Iniciar Vuelo"**
   → `POST /missions/{id}/start` (202; solo ADMIN).
2. Redirección automática a **En Vivo**:
   - **Telemetría**: WS `ws://localhost:8000/api/v1/video/ws/telemetry`
     (petición `"status"` cada 2 s) + polling `GET /telemetry/current` (5 s).
   - **Vuelo activo**: nombre de la misión + hito `waypoints_completados / total`.
   - **Tarjetas**: batería (voltaje), altitud, GPS (lat/lon), rumbo HDG.

## 6. Video en vivo (MJPEG)

El stream necesita frames publicados. En otra terminal:

```bash
cd drones-backend
# JWT admin: POST /auth/login o cópialo de localStorage["aeroluferan_session"].token
export DRONE_API_TOKEN=<jwt>
venv/bin/python scripts/run_camera_stream.py --source synthetic --fps 10
# o video real grabado: --source data/sitl-demo.mp4
```

En **En Vivo** aparece el MJPEG de `GET /video/live` (`<img>`), con
`/video/snapshot` para capturas y `/video/stream-info` para métricas.

## 7. Disparar una detección → alerta

El pipeline real es dron→backend (visión); para la demo se ingesta a mano —
`/detections/ingest` es público:

```bash
curl -X POST http://localhost:8000/api/v1/detections/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "tipo": "PERSONA",
    "nivel_confianza": 0.93,
    "latitud": 20.7035,
    "longitud": -100.4438
  }'
```

**Resultado:** la alerta llega por WS `/alerts/ws/notifications` y aparece en
**Alertas** (`/admin/alertas` y `/guardia/alertas`) con evidencia
(`/events`, `/alerts`).

## 8. Despachar guardia + emergencia

1. En **Alertas** usar la acción de despacho (notifica al perfil Guardia).
2. En **En Vivo**, las acciones reales disponibles (ADMIN y GUARDIA):
   - **Volver a Base** → `POST /drone/rtl` (RTL y aterrizaje).
   - **Detener Vuelo / Parada Inmediata** → también RTL (es la única acción
     de emergencia que expone el backend — no hay kill-switch).
   - **Pausar Vuelo** → cancela la misión EN_CURSO (equivalente real;
     `Reanudar` explica que no existe reanudación).

## 9. Cancelación y recuperación

1. **"Cancelar"** en la tarjeta de la misión (ADMIN o GUARDIA):
   - PROGRAMADA → `CANCELADA` directo.
   - EN_CURSO → `CANCELANDO` (el ejecutor manda RTL) → si el proceso se
     interrumpe, la misión queda en `RECUPERACION`.
2. En `RECUPERACION`: botón **"Confirmar aterrizaje"** en la tarjeta
   → `POST /missions/{id}/confirm-landed` → `FINALIZADA`.

## 10. Bitácora y evidencia

- **Bitácora** (`/admin/bitacora`, `/guardia/bitacora`): `GET /telemetry/log`
  — tabla paginada con filtros por misión/enlace.
- **Grabaciones**: `GET /recordings` — segmentos cifrados con checksum;
  `record_stream.py` graba el MJPEG en segmentos:
  `python scripts/record_stream.py --source http://127.0.0.1:8000/api/v1/video/live --segment-seconds 10 --vuelo-id 1`
- **Exportación**: desde **Ajustes** se genera el archivo de auditoría.

## 11. Base de carga (helipuerto)

- Tarjeta de helipuerto en **En Vivo** y modal en **Ajustes**:
  `GET /drone/charging-base` (estado IDLE/DOCKED/CHARGING/CHARGED + batería).
- Solo ADMIN: **"Acoplar y recargar"** → `POST /drone/charging-base/dock-recharge`.

---

## Resolución de problemas

| Síntoma | Causa probable | Acción |
|---|---|---|
| Badge siempre "Sin Señal" | Backend sin dron | SITL + MAVProxy arriba, luego clic en el badge (o `--no-sitl` explica el 503) |
| Tarjetas con "—" | Backend caído o sin login | `scripts/logs/backend.log`; reingresar sesión |
| Video "SIN SEÑAL" | Nadie publica frames | `run_camera_stream.py --source synthetic` con `DRONE_API_TOKEN` |
| Misión no inicia (503) | Dron no conectado | Paso 2 primero |
| Misión no inicia (409) | Estado ≠ PROGRAMADA o vehículo reservado | Revisar `estado` de la tarjeta |
| 422 al crear misión | Waypoint fuera de geocerca / fuera de ventana 06:00–23:00 | Redibujar puntos dentro de la zona activa |
| Alertas vacías | Sin detecciones ingeridas | Paso 7 (curl) |
