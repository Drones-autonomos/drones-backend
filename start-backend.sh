#!/usr/bin/env bash
# ============================================================================
# start-backend.sh — Levanta TODO el entorno Backend en UNA SOLA TERMINAL:
#   1. PostgreSQL (docker compose up -d db) + migraciones (alembic upgrade head)
#   2. Seed automático (roles, usuarios demo, helipuertos y geocerca Campus FIF)
#   3. Simulador ArduPilot SITL + MAVProxy (127.0.0.1:5760 -> udp:127.0.0.1:14550)
#   4. API FastAPI (uvicorn en http://localhost:8000)
#   5. Auto-conexión MAVLink del dron (POST /api/v1/drone/connect)
#   6. Cámara en vivo simulada sobre mapa satelital (scripts/run_telemetry_camera.py)
#
# Ctrl+C detiene limpiamente SITL, MAVProxy, Cámara y FastAPI.
# ============================================================================

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$BACKEND_DIR/venv"
LOG_DIR="$BACKEND_DIR/scripts/logs"
SITL_BIN="$HOME/.dronekit/sitl/copter-3.3/apm"
mkdir -p "$LOG_DIR"

log()  { printf '\033[1;36m[backend]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[backend]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[backend]\033[0m %s\n' "$*" >&2; exit 1; }

[[ -x "$VENV_DIR/bin/python" ]] || die "No se encontró el virtualenv en $VENV_DIR"

DC=()
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
fi

PIDS=()
cleanup() {
  trap - INT TERM EXIT
  echo
  log "Deteniendo procesos del backend (FastAPI, Cámara, MAVProxy, SITL)..."
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] || continue
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  sleep 1
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] || continue
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  done
  log "Backend detenido limpiamente."
}
trap cleanup INT TERM EXIT

launch_bg() {
  local name="$1"
  shift
  ( cd "$BACKEND_DIR" && exec setsid "$@" ) >"$LOG_DIR/$name.log" 2>&1 < /dev/null &
  local pid=$!
  PIDS+=("$pid")
  log "$name iniciado (pid $pid) -> scripts/logs/$name.log"
}

port_tcp_open() { ss -tlnH "sport = :$1" 2>/dev/null | grep -q .; }
port_udp_open() { ss -lunH "sport = :$1" 2>/dev/null | grep -q .; }

# 1. PostgreSQL
if port_tcp_open 5432; then
  log "PostgreSQL activo en :5432"
elif ((${#DC[@]})); then
  log "Levantando contenedor PostgreSQL (docker compose up -d db)..."
  "${DC[@]}" -f "$BACKEND_DIR/docker-compose.yml" up -d db
  for _ in $(seq 1 30); do
    if "${DC[@]}" -f "$BACKEND_DIR/docker-compose.yml" exec -T db pg_isready -U drone_user -d drone_db >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
else
  die "PostgreSQL no escucha en :5432 y docker compose no está disponible."
fi

# 2. Migraciones + Seed completo (usuarios demo + helipuertos + geocerca Campus FIF)
log "Aplicando migraciones Alembic (upgrade head)..."
( cd "$BACKEND_DIR" && "$VENV_DIR/bin/alembic" upgrade head )

log "Verificando usuarios demo, estaciones de carga y geocerca operativa..."
(
  cd "$BACKEND_DIR" && "$VENV_DIR/bin/python" - <<'PY'
from app.db.session import SessionLocal
from app.models.geofence import Geocerca
from app.services.charging_base_service import charging_base_service
from app.services.seed_service import ensure_roles_and_demo_users

db = SessionLocal()
try:
    ensure_roles_and_demo_users(db, seed_demo_users=True)
    charging_base_service.ensure_default_stations(db)
    if db.query(Geocerca).count() == 0:
        db.add(
            Geocerca(
                nombre="Perímetro Operativo Campus FIF Juriquilla",
                tipo="CIRCULAR",
                activa=True,
                centro_lat=20.70428,
                centro_lon=-100.44358,
                radio_metros=850.0,
                altitud_min_m=2.0,
                altitud_max_m=120.0,
                descripcion="Zona autorizada de patrullaje autónomo UAQ Campus Juriquilla",
                codigo_badge="GEO-FIF-01",
            )
        )
        db.commit()
finally:
    db.close()
PY
)

# 3. Simulador ArduPilot SITL + MAVProxy
HAVE_SITL=0
if port_tcp_open 5760; then
  log "SITL ya activo en tcp:127.0.0.1:5760"
  HAVE_SITL=1
elif [[ -x "$SITL_BIN" ]]; then
  launch_bg "sitl" bash scripts/run_sitl.sh
  for _ in $(seq 1 15); do
    if port_tcp_open 5760; then
      HAVE_SITL=1
      break
    fi
    sleep 1
  done
else
  warn "Binario SITL no encontrado en $SITL_BIN — se continuará con cámara simulada."
fi

if (( HAVE_SITL )); then
  if port_udp_open 14550; then
    log "MAVProxy / relay MAVLink ya activo en udp:127.0.0.1:14550"
  elif [[ -x "$VENV_DIR/bin/mavproxy.py" ]]; then
    launch_bg "mavproxy" "$VENV_DIR/bin/mavproxy.py" --master tcp:127.0.0.1:5760 --out udp:127.0.0.1:14550
    sleep 3
  fi
fi

# 4. API FastAPI
if port_tcp_open 8000; then
  warn "El puerto :8000 ya estaba en uso; reutilizando instancia activa."
else
  launch_bg "uvicorn" "$VENV_DIR/bin/uvicorn" app.main:app --reload --host 0.0.0.0 --port 8000
fi

log "Esperando a que FastAPI responda en http://127.0.0.1:8000/api/v1/ ..."
for _ in $(seq 1 40); do
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 2 http://127.0.0.1:8000/api/v1/ 2>/dev/null || true)"
  if [[ "$code" != "000" ]]; then
    break
  fi
  sleep 1
done

# 5. Generar JWT Admin para auto-conectar el dron y alimentar la cámara en vivo
ADMIN_TOKEN="$(
  cd "$BACKEND_DIR" && "$VENV_DIR/bin/python" - <<'PY'
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models.user import Rol, Usuario

db = SessionLocal()
try:
    admin = (
        db.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(Rol.nombre == "ADMIN", Usuario.activo == True)  # noqa: E712
        .order_by(Usuario.id.asc())
        .first()
    )
    if admin:
        print(create_access_token(subject=admin.id, rol="ADMIN"))
finally:
    db.close()
PY
)"

if [[ -n "$ADMIN_TOKEN" ]]; then
  if (( HAVE_SITL )); then
    log "Auto-conectando dron simulado vía MAVLink (udp:127.0.0.1:14550)..."
    curl -s -X POST "http://127.0.0.1:8000/api/v1/drone/connect?connection_string=udp:127.0.0.1:14550" \
      -H "Authorization: Bearer $ADMIN_TOKEN" >/dev/null || warn "No se pudo auto-conectar SITL (puedes reconectar desde la UI)."
  fi

  log "Iniciando stream de video en vivo hacia /api/v1/video/live ..."
  launch_bg "camera" "$VENV_DIR/bin/python" scripts/run_telemetry_camera.py --token "$ADMIN_TOKEN" --fps 10
fi

cat <<EOF

============================================================================
  BACKEND AEROLUFERAN LISTO EN UNA SOLA TERMINAL
============================================================================
  API REST   : http://localhost:8000/api/v1
  Swagger    : http://localhost:8000/docs
  Stream     : http://localhost:8000/api/v1/video/live
  Admin Demo : academico@uaq.mx  /  academico
  Guard Demo : seguridad@uaq.mx  /  seguridad
----------------------------------------------------------------------------
  En otra terminal ejecuta únicamente el Frontend:
    cd /home/ferram/Personal/UAQ/drones-autonomos/drones-frontend && npm run dev
============================================================================
  Mostrando logs en vivo de FastAPI (Ctrl+C para apagar todo el backend)...
EOF

if [[ -f "$LOG_DIR/uvicorn.log" ]]; then
  tail -f "$LOG_DIR/uvicorn.log"
else
  wait
fi
