# Plan de trabajo y evidencia

Revisión inicial: 25 de octubre de 2026. Alcance: este repositorio backend.

| Fase | Entregable | Estado |
|---|---|---|
| 1. Base estable | Permisos, configuración obligatoria, bootstrap local, contenedor verificable y demo SITL | En curso |
| 2. Misiones dinámicas | Ejecutor de waypoints persistidos, inicio por API y horario, progreso y estados | Implementada; validación SITL pendiente |
| 3. Telemetría y cancelación | Estado del vehículo, interrupción con RTL confirmado, tiempos máximos y desconexiones | Parcial: cancelación con RTL, tiempos máximos y recuperación implementados; falta exponer telemetría |
| 4. Integración de vuelo | Pruebas PostgreSQL + SITL, documentación y demo integrada | Pendiente; existen pruebas API + SQLite |
| 5. Video | Fuente simulada, servidor y reproducción, reconexión y medición de latencia | Pendiente |
| 6. Detección | Pipeline de frames, personas, humo y evaluación con datos separados | Pendiente |
| 7. Alertas y validación | Persistencia de eventos, reglas, deduplicación, evidencia y tiempos end-to-end | Pendiente |

## Cambios de fase 1

- Registro de usuarios restringido a ADMIN. Bootstrap local con `python -m app.bootstrap_admin`, tras las migraciones. No promueve cuentas existentes y rechaza un segundo bootstrap cuando ya existe ADMIN.
- Conexión y despegue restringidos a ADMIN; RTL permitido a ADMIN y GUARDIA.
- Altitud de despegue finita, entre 2 y 200 metros.
- `SECRET_KEY` obligatoria, mínimo 32 caracteres, sin valor de respaldo en código ni secreto en la plantilla.
- Docker instala `requirements.txt`, ejecuta como usuario sin privilegios y excluye `.env`, entornos y artefactos locales del contexto.
- Workflow de contenedor comprueba arranque HTTP. No publica ni despliega.
- Dependencia `future` declarada para que DroneKit pueda importar `past.builtins`; CI comprueba también la disponibilidad del servicio de vuelo sin conectar a un vehículo.
- Pruebas aisladas de la configuración local: clave efímera y SQLite en memoria.

## Verificación

- Suite: 70 pruebas aprobadas en el entorno local fuera del sandbox. Dentro del sandbox, TestClient se bloquea antes de ejecutar las peticiones.
- Ruff: lint y formato aprobados.
- Imagen Docker construida y respuesta HTTP 200 comprobada como usuario sin privilegios, sin copiar `.env` ni `.aws`. Suite de 70 pruebas aprobada también en Python 3.11 dentro del contenedor.
- Tras añadir `future`, la imagen se reconstruyó y se verificaron nuevamente la importación de DroneKit y el arranque HTTP; no se conectó a ningún vehículo.
- Los tests de permisos sustituyen el servicio de vuelo; no mandan comandos a un dron.
- La fase 1 no se cierra hasta reproducir y registrar la demo SITL. No hay evidencia nueva de vuelo ni de aterrizaje confirmado.
- El smoke test HTTP del contenedor no valida migraciones, PostgreSQL ni el enlace SITL.

## Próximos criterios de aceptación

1. Completar fase 1: levantar un SITL aislado, ejecutar la demo, comprobar llegada y aterrizaje y registrar evidencia. Mantener desactivaciones de geofence y prearmado limitadas a simulación.
2. Fases 2 y 3: crear dos rutas diferentes desde la API y ejecutarlas sin editar scripts; confirmar progreso, fin y cancelación mediante datos del simulador. Incorporar exclusión de vuelos simultáneos y límites de espera.
3. Fase 4: comprobar flujo completo y fallos con PostgreSQL y SITL, incluyendo migraciones y reinicios.
4. Fase 5: reproducir video continuo y documentar reconexión y latencia.
5. Fase 6: reportar precisión, recall y falsos positivos por detector con datos de evaluación independientes.
6. Fase 7: generar una alerta consultable con misión, ubicación, tiempo y evidencia; medir latencias p50/p95 y evitar alertas duplicadas.

No se asignan fechas hasta conocer disponibilidad del equipo y fuente de video. El bloque de video puede avanzar en paralelo al vuelo tras acordar contratos de integración.


## Avance de fase 2

Implementado el ejecutor de rutas persistidas, inicio manual por API, progreso y resultados en BD, exclusión de vuelos simultáneos y planificador opcional. La migración `6bf21ac304de` añade una reserva exclusiva del vehículo que se conserva si no se confirma aterrizaje. Se adelantó la cancelación mínima de fase 3 para poder interrumpir rutas y recuperar reservas tras reinicios.

La migración se verificó en SQLite con upgrade, downgrade y nuevo upgrade conservando una misión previa. El flujo de vuelo está probado con dobles de vehículo e hilo real; todavía no hay evidencia nueva de SITL ni integración PostgreSQL + SITL. Las fases 1 y 2 conservan pendiente esa aceptación de vuelo. Instrucciones en [MISSION_EXECUTION.md](MISSION_EXECUTION.md).

Verificación de fase 2: 111 pruebas aprobadas localmente; Ruff y formato aprobados. Imagen `drones-backend:phase2-review` construida localmente.
