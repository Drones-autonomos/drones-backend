# Plan de trabajo y evidencia

Revisión actualizada: 17 de noviembre de 2026. Alcance: este repositorio backend, simulación y control.

| Fase | Entregable | Estado |
|---|---|---|
| 1. Base estable | Permisos, configuración obligatoria, bootstrap local, contenedor verificable y demo SITL | Implementada |
| 2. Misiones dinámicas | Ejecutor de waypoints persistidos, inicio por API y horario, progreso y estados | Implementada y probada |
| 3. Telemetría y cancelación | Estado del vehículo, interrupción con RTL confirmado, bitácora y desconexiones | Implementada y probada |
| 4. Integración y normativa | Pruebas API + SQLite, geocercas, límites normativos en script/controlador, failsafe y base de carga | Implementada y probada |
| 5. Video y grabación | Stream en vivo MJPEG/WebSocket, cámara simulada, grabación segmentada con ffmpeg y cifrado AES-GCM | Implementada y probada |
| 6. Detección | Pipeline de frames OpenCV, detector de personas YOLOv8n ONNX, detector de humo y evaluación de umbrales | Implementada y probada |
| 7. Alertas y validación E2E | Persistencia de eventos, reglas, alertas en tiempo real, bitácora y flujo integral simulado | Implementada y probada |

## Módulos implementados

- **Normativa y control (`app/core/normative.py`, `app/schemas/mission.py`, `scripts/drone_backend.py`)**: Validación unificada de altitud (2–200 m), peso (<= 5 kg) y ventana operativa (06:00–23:00 hrs) conectada a `/api/v1/settings/operating-window`.
- **Visión (`app/vision/`)**: `FramePipeline` (OpenCV), `PersonDetector` (YOLOv8n ONNX), `SmokeDetector`, `evaluate_detector` / `tune_threshold`, y `VisionPipelineRunner` hacia `/api/v1/detections/ingest`.
- **Streaming (`app/services/video_stream_service.py`, `app/api/v1/endpoints/video.py`, `scripts/run_camera_stream.py`)**: Publicación de frames, `/api/v1/video/live` (MJPEG), `/snapshot`, `/stream-info` con conteo de reconexiones y WebSocket `/ws/telemetry`.
- **Grabación continua (`app/services/recording_pipeline.py`, `scripts/record_stream.py`)**: Segmentación MP4 con `ffmpeg` (keyframes forzados por segmento) y carga automática con metadata hacia `/api/v1/recordings/upload` (cifrado AES-GCM y purga a 30 días).
- **Telemetría (`app/models/telemetry.py`, `app/services/telemetry_service.py`, `app/api/v1/endpoints/telemetry.py`)**: Snapshots en vivo (`/current`) y bitácora histórica persistente (`/log`) integrada al ciclo de ejecución de misiones.
- **Geocercas (`app/models/geofence.py`, `app/services/geofence_service.py`, `app/api/v1/endpoints/geofence.py`)**: Geocercas circulares y poligonales (`shapely`) validadas en creación/inicio de misiones y en `DroneService.goto_waypoint`.
- **Failsafe y base de carga (`app/services/drone_service.py`, `app/services/charging_base_service.py`)**: Configuración de `FS_GCS_ENABLE=1` (RTL), excepción `SignalLossError` con recuperación de reserva, y acoplamiento/recarga simulada en HOME (`/api/v1/drone/charging-base/dock-recharge`).
- **Flujo integral (`scripts/run_integral_demo.py`, `tests/test_integral_mission.py`)**: Verificación conjunta de geocerca, misión, telemetría, stream, visión, alerta y recarga.
