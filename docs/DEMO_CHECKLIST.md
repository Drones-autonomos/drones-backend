# Checklist de Demostración, Respaldo y Entrega (Sprints 1–6)

## 1. Pre-vuelo y CI/CD
- [ ] Verificar estilo y pruebas automatizadas:
  ```bash
  ruff check .
  ruff format --check .
  pytest
  ```
- [ ] Aplicar migraciones pendientes antes de iniciar la API:
  ```bash
  alembic upgrade head
  ```
- [ ] Crear administrador inicial si la BD está vacía:
  ```bash
  python -m app.bootstrap_admin
  ```

## 2. Arranque de entorno en vivo
- [ ] Terminal 1 (Simulador SITL): `./scripts/run_sitl.sh`
- [ ] Terminal 2 (MAVProxy): `./scripts/run_mavproxy.sh`
- [ ] Terminal 3 (Backend): `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- [ ] Terminal 4 (Cámara simulada al stream): `python scripts/run_camera_stream.py --source data/sitl-demo.mp4 --token <JWT_ADMIN>`
- [ ] Terminal 5 (Grabación continua segmentada): `python scripts/record_stream.py --source http://127.0.0.1:8000/api/v1/video/live --segment-seconds 10 --vuelo-id 1`

## 3. Verificación funcional durante la demo
- [ ] Configurar geocerca operativa (`POST /api/v1/geofences/`) y validar rechazo de waypoint fuera de zona.
- [ ] Validar rechazo normativo por altitud > 200 m o fuera de ventana operativa (06:00–23:00 hrs).
- [ ] Conectar dron (`POST /api/v1/drone/connect`) y habilitar failsafe (`POST /api/v1/drone/failsafe?enabled=true`).
- [ ] Iniciar misión (`POST /api/v1/missions/{id}/start`), monitorear bitácora (`GET /api/v1/telemetry/log`) y cancelar/RTL si aplica.
- [ ] Verificar stream en vivo (`GET /api/v1/video/live`), detección de personas/humo y alerta WebSocket (`/api/v1/alerts/ws/notifications`).
- [ ] Confirmar almacenamiento cifrado (`GET /api/v1/recordings/`) y reproducción descifrada (`GET /api/v1/recordings/{id}/stream`).
- [ ] Ejecutar acoplamiento y recarga en base HOME (`POST /api/v1/drone/charging-base/dock-recharge`).

## 4. Plan de respaldo (sin hardware/SITL en vivo)
- [ ] Ejecutar la suite integral simulada:
  ```bash
  pytest tests/test_integral_mission.py tests/test_recording_pipeline.py tests/test_vision_integration.py
  ```
- [ ] Mostrar video de respaldo local (`data/sitl-demo.mp4`) y reporte SITL + PostgreSQL (`data/sitl-postgres-report.json`).

## 5. Registro de retroalimentación (Entrega Sprint 6)
| Fecha | Observación / Hallazgo | Módulo afectado | Prioridad | Responsable |
|---|---|---|---|---|
| 2026-11-17 | | | | |
