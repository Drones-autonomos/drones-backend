# Arquitectura del Sistema

## Visión General

El sistema de drones autónomos UAQ se compone de tres capas principales:

```
┌──────────────────────────────────────────────────────────────────┐
│                        Frontend / App Móvil                       │
│           (React / Flutter — repositorio separado)               │
└──────────────────────────┬───────────────────────────────────────┘
                           │  HTTP REST (JSON)
┌──────────────────────────▼───────────────────────────────────────┐
│                      Backend API (este repo)                      │
│                FastAPI · PostgreSQL · SQLAlchemy                  │
└────────────────────┬───────────────────────────┬─────────────────┘
                     │  DroneKit / MAVLink        │  SQL (psycopg2)
        ┌────────────▼─────────────┐   ┌─────────▼──────────────┐
        │  Simulador ArduPilot     │   │  PostgreSQL 15          │
        │  SITL + MAVProxy         │   │  (docker-compose)       │
        └──────────────────────────┘   └────────────────────────┘
```

---

## Estructura de la API

```
app/
├── main.py                  ← FastAPI app, CORS, router global
├── api/
│   ├── deps.py              ← Dependencias inyectables (get_db, RBAC)
│   └── v1/
│       ├── api.py           ← Router /api/v1/ — agrega todos los routers
│       └── endpoints/
│           ├── auth.py      ← /auth/ — register, login, me
│           ├── missions.py  ← /missions/ — CRUD de misiones
│           ├── drone.py     ← /drone/ — connect, takeoff, RTL
│           ├── alerts.py    ← /alerts/ — (en desarrollo)
│           └── telemetry.py ← /telemetry/ — (en desarrollo)
├── core/
│   ├── config.py            ← Settings desde .env (pydantic-settings)
│   └── security.py          ← JWT (python-jose) + hashing (passlib/bcrypt)
├── db/
│   ├── base_class.py        ← DeclarativeBase de SQLAlchemy
│   └── session.py           ← engine + SessionLocal (psycopg2)
├── models/                  ← ORM — mapeo Python ↔ tablas SQL
│   ├── user.py              ← Usuario, Rol, Permiso, rol_permiso (M:N)
│   └── mission.py           ← Mision, Ruta (waypoints)
├── schemas/                 ← Pydantic — validación de request/response
│   ├── user.py              ← UserCreate, UserLogin, UserResponse, RolResponse
│   ├── mission.py           ← MisionCreate, MisionUpdate, MisionResponse, Waypoint*
│   └── token.py             ← Token, TokenPayload
└── services/
    └── drone_service.py     ← Singleton DroneService (DroneKit, lazy import)
```

---

## Modelo de Datos

### Diagrama Entidad-Relación

```
┌─────────────────┐          ┌─────────────────────┐
│     permisos    │          │       misiones       │
├─────────────────┤    ┌─────├─────────────────────┤
│ id (PK)         │    │     │ id (PK)              │
│ nombre          │    │     │ creado_por → usuarios│
│ descripcion     │    │     │ nombre               │
└────────┬────────┘    │     │ descripcion          │
         │ M:N         │     │ estado               │
┌────────▼────────┐    │     │ horario_inicio_prog. │
│  roles_permisos │    │     │ created_at           │
├─────────────────┤    │     └──────────┬──────────┘
│ rol_id  (FK)    │    │                │ 1:N
│ permiso_id (FK) │    │     ┌──────────▼──────────┐
└────────┬────────┘    │     │        rutas         │
         │             │     ├─────────────────────┤
┌────────▼────────┐    │     │ id (PK)              │
│      roles      │    │     │ mision_id → misiones │
├─────────────────┤    │     │ orden_waypoint        │
│ id (PK)         │    │     │ latitud              │
│ nombre          │    │     │ longitud             │
│ descripcion     │    │     │ altitud_metros        │
│ created_at      │    │     └─────────────────────┘
└────────┬────────┘    │
         │ 1:N         │
┌────────▼────────┐    │
│    usuarios     │────┘
├─────────────────┤
│ id (PK)         │
│ rol_id (FK)     │
│ nombre          │
│ email (UNIQUE)  │
│ password_hash   │
│ activo          │
│ created_at      │
└─────────────────┘
```

### Estados de una Misión

```
    ┌──────────────┐
    │  PROGRAMADA  │ ← estado inicial al crear
    └──────┬───────┘
           │  (lanzamiento / inicio manual)
    ┌──────▼───────┐
    │   EN_CURSO   │
    └──────┬───────┘
           │  (aterrizaje exitoso)
    ┌──────▼───────┐
    │  FINALIZADA  │
    └──────────────┘
    
    Desde PROGRAMADA o EN_CURSO:
    ┌──────────────┐
    │  CANCELADA   │ ← POST /missions/{id}/cancel
    └──────────────┘
```

---

## Seguridad

### Autenticación JWT

```
Cliente                              API
  │                                   │
  │── POST /auth/login ──────────────►│
  │   { email, password }             │
  │                                   │── verify_password(plain, hash) ──► passlib/bcrypt
  │                                   │── create_access_token(user_id) ──► python-jose
  │◄─────────────────────────────────│
  │   { access_token, token_type }    │
  │                                   │
  │── GET /auth/me ─────────────────►│
  │   Authorization: Bearer <token>   │
  │                                   │── jwt.decode(token, SECRET_KEY)
  │                                   │── db.query(Usuario).filter(id=sub)
  │◄─────────────────────────────────│
  │   { id, nombre, email, rol... }   │
```

### Control de Acceso (RBAC)

Las rutas protegidas usan `Depends()` de FastAPI con la clase `RoleChecker`:

```python
# En cualquier endpoint protegido:
@router.post("/missions/", dependencies=[Depends(deps.require_admin)])
def create_mission(...):
    ...

# Roles disponibles:
require_admin          = RoleChecker(["ADMIN"])
require_guard_or_admin = RoleChecker(["ADMIN", "GUARDIA"])
```

---

## Stack Tecnológico

| Capa | Tecnología | Versión | Propósito |
|---|---|---|---|
| Framework web | FastAPI | ≥ 0.100 | API REST asíncrona |
| Servidor ASGI | Uvicorn | ≥ 0.30 | Servidor de producción |
| ORM | SQLAlchemy | ≥ 2.0 | Mapeo objeto-relacional |
| Migraciones | Alembic | ≥ 1.13 | Control de esquema de DB |
| Base de datos | PostgreSQL | ≥ 15 | Persistencia principal |
| Driver DB | psycopg2-binary | ≥ 2.9 | Adaptador Python→PostgreSQL |
| Validación | Pydantic v2 | ≥ 2.0 | Schemas y settings |
| Autenticación | python-jose | ≥ 3.3 | Firma y verificación JWT |
| Hashing | passlib + bcrypt | ≥ 1.7 + 4.x | Hash de contraseñas |
| Control dron | DroneKit | — | Protocolo MAVLink (lazy) |
| Linter | Ruff | ≥ 0.4 | Linting + formato |
| Testing | pytest | ≥ 7.0 | Suite de tests |
| CI/CD | GitHub Actions | — | Integración continua |

---

## Flujo de una Petición HTTP

```
Request HTTP
     │
     ▼
FastAPI (app/main.py)
     │  CORS Middleware
     │  Routing → /api/v1/...
     ▼
Endpoint Function (app/api/v1/endpoints/*.py)
     │  Depends(get_db)    → sesión de SQLAlchemy
     │  Depends(get_current_user) → JWT decode → query Usuario
     │  Depends(require_admin)    → RBAC check
     ▼
Lógica de negocio
     │  db.query(Model).filter(...)
     │  db.add(obj) / db.commit()
     ▼
Schema Pydantic (Response)
     │  Serialización → JSON
     ▼
Response HTTP
```
