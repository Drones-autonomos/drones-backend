# API Reference — Drones Autónomos v1

Base URL: `http://localhost:8000/api/v1`

> Todos los endpoints que requieren autenticación esperan el header:
> ```
> Authorization: Bearer <token>
> ```

---

## Índice

- [Autenticación](#autenticación)
  - [POST /auth/register](#post-authregister)
  - [POST /auth/login](#post-authlogin)
  - [GET /auth/me](#get-authme)
- [Misiones](#misiones)
  - [POST /missions/](#post-missions)
  - [GET /missions/](#get-missions)
  - [GET /missions/{id}](#get-missionsid)
  - [PUT /missions/{id}](#put-missionsid)
  - [POST /missions/{id}/cancel](#post-missionsidcancel)
- [Control de Vuelo](#control-de-vuelo)
  - [POST /drone/connect](#post-droneconnect)
  - [POST /drone/takeoff](#post-dronetakeoff)
  - [POST /drone/rtl](#post-dronetl)
- [Roles y Permisos](#roles-y-permisos)
- [Códigos de Error](#códigos-de-error)

---

## Autenticación

### POST /auth/register

Registra un nuevo usuario en el sistema.

**Requiere autenticación:** No  
**Roles permitidos:** Público

**Request Body**

```json
{
  "nombre": "Juan Pérez",
  "email": "juan@facultad.edu.mx",
  "password": "MiPassword123!",
  "rol_id": 2
}
```

| Campo | Tipo | Requerido | Validación |
|---|---|---|---|
| `nombre` | string | ✅ | 2–100 caracteres |
| `email` | string (email) | ✅ | Formato válido, único en sistema |
| `password` | string | ✅ | Mínimo 6 caracteres |
| `rol_id` | integer | ✅ | `1` = ADMIN, `2` = GUARDIA |

**Response 201 — Created**

```json
{
  "id": 3,
  "nombre": "Juan Pérez",
  "email": "juan@facultad.edu.mx",
  "activo": true,
  "rol": {
    "id": 2,
    "nombre": "GUARDIA",
    "descripcion": "Guardia de seguridad de la facultad"
  },
  "created_at": "2026-09-29T16:00:00"
}
```

**Errores posibles**

| Código | Causa |
|---|---|
| `400` | El correo electrónico ya está registrado |
| `404` | El `rol_id` especificado no existe |
| `422` | Error de validación (nombre muy corto, password corta, email inválido) |

---

### POST /auth/login

Autentica un usuario y devuelve un token JWT Bearer.

**Requiere autenticación:** No  
**Roles permitidos:** Público

**Request Body**

```json
{
  "email": "juan@facultad.edu.mx",
  "password": "MiPassword123!"
}
```

**Response 200 — OK**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

> El token tiene validez de **8 horas** (configurable en `ACCESS_TOKEN_EXPIRE_MINUTES`).

**Errores posibles**

| Código | Causa |
|---|---|
| `400` | Usuario inactivo en el sistema |
| `401` | Correo o contraseña incorrectos |
| `422` | Formato de email inválido |

---

### GET /auth/me

Retorna el perfil del usuario autenticado.

**Requiere autenticación:** ✅ (Bearer Token)  
**Roles permitidos:** `ADMIN`, `GUARDIA`

**Response 200 — OK**

```json
{
  "id": 3,
  "nombre": "Juan Pérez",
  "email": "juan@facultad.edu.mx",
  "activo": true,
  "rol": {
    "id": 2,
    "nombre": "GUARDIA",
    "descripcion": "Guardia de seguridad de la facultad"
  },
  "created_at": "2026-09-29T16:00:00"
}
```

**Errores posibles**

| Código | Causa |
|---|---|
| `401` | Token ausente, expirado o inválido |
| `404` | Usuario no encontrado (cuenta eliminada) |

---

## Misiones

### POST /missions/

Crea una nueva misión de patrullaje con waypoints.

**Requiere autenticación:** ✅  
**Roles permitidos:** `ADMIN` únicamente

**Request Body**

```json
{
  "nombre": "Patrulla Nocturna Sector Norte",
  "descripcion": "Recorrido perimetral del edificio principal",
  "horario_inicio_programado": "2026-10-01T22:00:00",
  "waypoints": [
    {
      "orden_waypoint": 1,
      "latitud": 20.70428,
      "longitud": -100.44358,
      "altitud_metros": 20.0
    },
    {
      "orden_waypoint": 2,
      "latitud": 20.70600,
      "longitud": -100.44200,
      "altitud_metros": 20.0
    },
    {
      "orden_waypoint": 3,
      "latitud": 20.70428,
      "longitud": -100.44358,
      "altitud_metros": 10.0
    }
  ]
}
```

| Campo | Tipo | Requerido | Validación |
|---|---|---|---|
| `nombre` | string | ✅ | 3–100 caracteres |
| `descripcion` | string | ❌ | Texto libre |
| `horario_inicio_programado` | datetime (ISO 8601) | ❌ | — |
| `waypoints` | array | ✅ | Mínimo **2** waypoints |
| `waypoints[].orden_waypoint` | integer | ✅ | ≥ 1 |
| `waypoints[].latitud` | float | ✅ | −90.0 a 90.0 |
| `waypoints[].longitud` | float | ✅ | −180.0 a 180.0 |
| `waypoints[].altitud_metros` | float | ❌ | 2.0 a 200.0 (default: 15.0) |

**Response 201 — Created**

```json
{
  "id": 1,
  "nombre": "Patrulla Nocturna Sector Norte",
  "descripcion": "Recorrido perimetral del edificio principal",
  "estado": "PROGRAMADA",
  "creado_por": 1,
  "horario_inicio_programado": "2026-10-01T22:00:00",
  "created_at": "2026-09-29T16:00:00",
  "waypoints": [
    { "id": 1, "orden_waypoint": 1, "latitud": 20.70428, "longitud": -100.44358, "altitud_metros": 20.0 },
    { "id": 2, "orden_waypoint": 2, "latitud": 20.70600, "longitud": -100.44200, "altitud_metros": 20.0 },
    { "id": 3, "orden_waypoint": 3, "latitud": 20.70428, "longitud": -100.44358, "altitud_metros": 10.0 }
  ]
}
```

**Errores posibles**

| Código | Causa |
|---|---|
| `401` | Sin autenticación |
| `403` | Rol insuficiente (GUARDIA no puede crear misiones) |
| `422` | Menos de 2 waypoints, nombre muy corto, coordenadas fuera de rango |

---

### GET /missions/

Lista todas las misiones con soporte de filtros y paginación.

**Requiere autenticación:** ✅  
**Roles permitidos:** `ADMIN`, `GUARDIA`

**Query Parameters**

| Parámetro | Tipo | Default | Descripción |
|---|---|---|---|
| `estado` | string | — | Filtrar por estado: `PROGRAMADA`, `EN_CURSO`, `FINALIZADA`, `CANCELADA` |
| `skip` | integer | `0` | Registros a saltar (offset) |
| `limit` | integer | `50` | Máximo registros devueltos (1–100) |

**Ejemplo de request**

```
GET /api/v1/missions/?estado=PROGRAMADA&skip=0&limit=10
```

**Response 200 — OK**

```json
[
  {
    "id": 1,
    "nombre": "Patrulla Nocturna Sector Norte",
    "estado": "PROGRAMADA",
    "creado_por": 1,
    "created_at": "2026-09-29T16:00:00",
    "waypoints": [...]
  }
]
```

---

### GET /missions/{id}

Retorna el detalle completo de una misión por su ID.

**Requiere autenticación:** ✅  
**Roles permitidos:** `ADMIN`, `GUARDIA`

**Path Parameters**

| Parámetro | Tipo | Descripción |
|---|---|---|
| `id` | integer | ID de la misión |

**Response 200 — OK** — igual al objeto de misión completo (ver POST).

**Errores posibles**

| Código | Causa |
|---|---|
| `404` | Misión no encontrada |

---

### PUT /missions/{id}

Edita los datos informativos de una misión. Solo funciona si la misión está en estado `PROGRAMADA`.

**Requiere autenticación:** ✅  
**Roles permitidos:** `ADMIN` únicamente

**Request Body** (todos los campos opcionales)

```json
{
  "nombre": "Patrulla Sector Norte — Actualizada",
  "descripcion": "Nueva descripción de la misión",
  "horario_inicio_programado": "2026-10-02T21:00:00"
}
```

**Response 200 — OK** — objeto de misión actualizado.

**Errores posibles**

| Código | Causa |
|---|---|
| `400` | La misión no está en estado `PROGRAMADA` |
| `403` | Rol insuficiente |
| `404` | Misión no encontrada |

---

### POST /missions/{id}/cancel

Cancela una misión (cambia su estado a `CANCELADA`).

**Requiere autenticación:** ✅  
**Roles permitidos:** `ADMIN`, `GUARDIA`

**Response 200 — OK**

```json
{
  "id": 1,
  "estado": "CANCELADA",
  ...
}
```

**Errores posibles**

| Código | Causa |
|---|---|
| `400` | La misión ya está `CANCELADA` o `FINALIZADA` |
| `404` | Misión no encontrada |

---

## Control de Vuelo

> ⚠️ Estos endpoints requieren que el servidor SITL esté corriendo y MAVProxy haya ruteado la telemetría a `udp:127.0.0.1:14550`. Ver [Guía de Simulación SITL](SITL_SIMULATION.md).

### POST /drone/connect

Establece conexión con el dron via MAVLink.

**Requiere autenticación:** No (por ahora)

**Request Body**

```json
{
  "connection_string": "127.0.0.1:14550"
}
```

**Response 200 — OK**

```json
{ "message": "Dron conectado exitosamente" }
```

---

### POST /drone/takeoff

Arma los motores y ejecuta el despegue a la altitud especificada.

**Request Body**

```json
{
  "altitude": 10.0
}
```

**Response 200 — OK**

```json
{ "message": "Despegue completado a 10.0 metros" }
```

> ⚠️ Esta operación es bloqueante — espera hasta alcanzar el 95% de la altitud objetivo.

---

### POST /drone/rtl

Envía el comando **Return to Launch** (volver a la base y aterrizar).

**Response 200 — OK**

```json
{ "message": "Regresando a base" }
```

---

## Roles y Permisos

| Endpoint | ADMIN | GUARDIA | Público |
|---|:---:|:---:|:---:|
| `POST /auth/register` | ✅ | ✅ | ✅ |
| `POST /auth/login` | ✅ | ✅ | ✅ |
| `GET /auth/me` | ✅ | ✅ | ❌ |
| `POST /missions/` | ✅ | ❌ | ❌ |
| `GET /missions/` | ✅ | ✅ | ❌ |
| `GET /missions/{id}` | ✅ | ✅ | ❌ |
| `PUT /missions/{id}` | ✅ | ❌ | ❌ |
| `POST /missions/{id}/cancel` | ✅ | ✅ | ❌ |
| `POST /drone/*` | ✅ | ✅ | ❌ |

---

## Códigos de Error

Todos los errores siguen el formato estándar de FastAPI:

```json
{
  "detail": "Descripción del error"
}
```

Los errores de validación (422) incluyen detalles por campo:

```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    }
  ]
}
```

| Código | Significado |
|---|---|
| `200` | OK |
| `201` | Creado exitosamente |
| `400` | Error de lógica de negocio (regla violada) |
| `401` | No autenticado o token inválido |
| `403` | Autenticado pero sin permiso (rol insuficiente) |
| `404` | Recurso no encontrado |
| `422` | Error de validación del body/query |
| `500` | Error interno del servidor |
