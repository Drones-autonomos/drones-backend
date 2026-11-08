# Ejecución de misiones desde el backend

## Preparación

1. Detener la API y aplicar `alembic upgrade head`. La revisión `6bf21ac304de` conserva las rutas existentes y añade progreso, marcas de tiempo, error y una reserva exclusiva del vehículo.
2. Iniciar la API con **un único worker y una única instancia de control**. Los bloqueos de comandos y el planificador viven en ese proceso. La reserva en BD evita iniciar una segunda misión y sobrevive reinicios; no sustituye un coordinador distribuido.
3. Iniciar SITL y MAVProxy siguiendo [la guía de simulación](SITL_SIMULATION.md).
4. Iniciar sesión como ADMIN y enviar el token Bearer en todas las peticiones de control.
5. Conectar mediante `POST /api/v1/drone/connect`. El ejecutor exige conexión con telemetría reciente, vehículo desarmado y altura relativa de hasta un metro.

La suite automatizada sustituye el vehículo por dobles de prueba; todavía falta validar este flujo con SITL y registrar evidencia de vuelo real del simulador.

## Crear, iniciar y observar una ruta

`POST /api/v1/missions/` recibe, por ejemplo:

```json
{
  "nombre": "Patrulla de prueba",
  "waypoints": [
    {"orden_waypoint": 1, "latitud": 20.7044, "longitud": -100.4435, "altitud_metros": 10},
    {"orden_waypoint": 2, "latitud": 20.7046, "longitud": -100.4434, "altitud_metros": 12}
  ]
}
```

Los órdenes deben ser únicos y consecutivos desde 1. Se aceptan puntos enviados en cualquier orden y se ejecutan ordenados. Las coordenadas y alturas deben ser finitas y estar dentro de los rangos del esquema. No se implementan todavía geofences ni validación de obstáculos.

Enviar `POST /api/v1/missions/{id}/start` como ADMIN. Devuelve **202** con el registro de la misión y no espera a que termine el vuelo. El inicio manual no espera al horario guardado. La misión pasa a `EN_CURSO` antes de lanzar su hilo; un segundo inicio se rechaza con 409.

Consultar `GET /api/v1/missions/{id}` como ADMIN o GUARDIA. Además de los campos existentes, devuelve:

- `iniciada_at` y `finalizada_at`.
- `waypoints_completados`: cantidad de puntos cuya llegada se confirmó.
- `error_ejecucion`: explicación del fallo o de una recuperación pendiente.

El vuelo despega a la altura del primer punto, navega por cada waypoint y vuelve en RTL. La llegada requiere distancia horizontal de hasta 3 metros y diferencia vertical de hasta 1 metro. Se comprueba la telemetría periódicamente; un heartbeat de más de 5 segundos se considera desactualizado. Los tiempos máximos por espera son 90 segundos para etapas del despegue y 180 segundos para cada waypoint o aterrizaje. Estos valores deben calibrarse con SITL antes de usarlos fuera de pruebas.

## Cancelación y errores

`POST /api/v1/missions/{id}/cancel` está permitido a ADMIN y GUARDIA:

| Situación | Resultado |
|---|---|
| Misión PROGRAMADA | CANCELADA inmediatamente; no se envían comandos de vuelo. |
| Misión EN_CURSO | CANCELANDO; el ejecutor interrumpe la navegación, solicita RTL y espera aterrizaje. |
| Aterrizaje confirmado tras cancelación | CANCELADA; se libera la reserva. |
| Ruta terminada y aterrizaje confirmado | FINALIZADA; se libera la reserva. |
| Error de navegación con aterrizaje confirmado | FALLIDA; se registra error y se libera la reserva. |
| Sin confirmación de aterrizaje | RECUPERACION; la reserva permanece y bloquea nuevos vuelos. |

Durante una misión, los comandos manuales de conexión y despegue se rechazan con 409. `/drone/rtl` solicita la cancelación de la misión activa para impedir que el ejecutor vuelva a enviar waypoints después de RTL. La respuesta indica una solicitud, no una confirmación de aterrizaje.

## Recuperación tras interrupción

Un reinicio no reanuda una misión ni borra su reserva. Si una ejecución quedó EN_CURSO, CANCELANDO o RECUPERACION sin ejecutor:

1. Reconectar al vehículo con `/drone/connect` si hace falta. La reconexión se permite con reserva pendiente cuando no hay un ejecutor activo.
2. Ordenar `/drone/rtl` si corresponde y esperar el aterrizaje.
3. Enviar `POST /api/v1/missions/{id}/confirm-landed` como ADMIN. Solo libera la reserva si la telemetría es reciente y el vehículo está desarmado y en tierra. La misión se registra como FALLIDA con recuperación confirmada.

Si el proceso se cierra normalmente, solicita cancelación y espera hasta 10 segundos al hilo de vuelo. Si el aterrizaje tarda más o el proceso se interrumpe, la reserva permanece. No eliminarla manualmente de la BD para iniciar otro vuelo sin verificar el estado del vehículo.

## Ejecución por horario

Por defecto `MISSION_SCHEDULER_ENABLED=false`: guardar un horario no inicia automáticamente el vuelo.

Para habilitarlo, definir `MISSION_SCHEDULER_ENABLED=true` y reiniciar la API con un solo worker. El planificador revisa cada 5 segundos las misiones PROGRAMADAS cuyo horario ya llegó, en orden de fecha e ID. Si el vehículo está ocupado o desconectado, quedan pendientes para el siguiente ciclo. Una misión terminada o fallida no se vuelve a ejecutar.

Las fechas con offset se convierten a UTC. Por compatibilidad, las fechas sin zona se interpretan como UTC; `2026-10-25T10:00:00-06:00` se guarda como `2026-10-25T16:00:00`. Una fecha nula requiere inicio manual. Al activar el planificador también son elegibles las misiones antiguas con fecha vencida; revisar la lista antes de habilitarlo.

## Verificación

Las pruebas incluyen rutas distintas, orden de waypoints, permisos, cancelación, exclusión mutua, fallo de telemetría, tiempos máximos, progreso, reserva tras fallo/reinicio, hilo real con vehículo simulado en memoria, planificador y migración de ida/vuelta conservando datos. No sustituyen las pruebas PostgreSQL + SITL de la fase de integración.
