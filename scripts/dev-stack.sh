#!/usr/bin/env bash
# ============================================================================
# dev-stack.sh — Orquestador del stack local completo (AeroLuferan)
#
# Vive en drones-backend/scripts/ y orquesta ambos repos del workspace
# (polirepo: asume drones-frontend/ como directorio hermano).
#
# Levanta, en un solo comando:
#   1. PostgreSQL            (docker compose, puerto 5432)
#   2. Migraciones Alembic   (alembic upgrade head)
#   3. ArduPilot SITL        (scripts/run_sitl.sh, campus UAQ Juriquilla)
#   4. MAVProxy              (reenvío MAVLink a udp:127.0.0.1:14550)
#   5. Backend FastAPI       (uvicorn --reload, puerto 8000)
#   6. Frontend Vite         (npm run dev, puerto 5173)
#
# Uso (desde cualquier directorio):
#   drones-backend/scripts/dev-stack.sh                  # stack completo
#   drones-backend/scripts/dev-stack.sh --no-sitl        # solo DB + API + frontend
#   drones-backend/scripts/dev-stack.sh --bootstrap-admin  # además crea el admin inicial
#   drones-backend/scripts/dev-stack.sh --with-gui       # MAVProxy con mapa/consola (X11)
#   drones-backend/scripts/dev-stack.sh --stop-db        # también detiene Postgres al salir
#
# Ctrl+C detiene todos los procesos hijos (cada uno en su propio grupo).
# Logs de cada servicio en drones-backend/scripts/logs/<nombre>.log
# ============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/drones-backend"
FRONTEND_DIR="$ROOT_DIR/drones-frontend"
VENV_DIR="$BACKEND_DIR/venv"
LOG_DIR="$BACKEND_DIR/scripts/logs"
SITL_BIN="$HOME/.dronekit/sitl/copter-3.3/apm"

WITH_SITL=1
WITH_GUI="${DISPLAY:+1}"   # GUI de MAVProxy solo si hay sesión gráfica
BOOTSTRAP_ADMIN=0
STOP_DB=0

for arg in "$@"; do
  case "$arg" in
    --no-sitl)         WITH_SITL=0 ;;
    --with-gui)        WITH_GUI=1 ;;
    --bootstrap-admin) BOOTSTRAP_ADMIN=1 ;;
    --stop-db)         STOP_DB=1 ;;
    -h|--help)
      sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "[stack] Opción desconocida: $arg (usa --help)" >&2
      exit 2
      ;;
  esac
done

# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------

log()  { printf '\033[1;34m[stack]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[stack]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[stack]\033[0m %s\n' "$*" >&2; exit 1; }

DC=()
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
fi

dc() { "${DC[@]}" -f "$BACKEND_DIR/docker-compose.yml" "$@"; }

PIDS=()
declare -A PID_NAMES=()
DB_STARTED=0

launch() {
  # launch <nombre> <directorio> <comando...>
  # Cada proceso corre con setsid → su pgid == su pid → kill al grupo entero.
  local name="$1" workdir="$2"
  shift 2
  mkdir -p "$LOG_DIR"
  ( cd "$workdir" && exec setsid "$@" ) >"$LOG_DIR/$name.log" 2>&1 < /dev/null &
  local pid=$!
  PIDS+=("$pid")
  PID_NAMES[$pid]="$name"
  log "$name iniciado (pid $pid) → drones-backend/scripts/logs/$name.log"
}

wait_http() {
  # wait_http <url> <timeout_s> — espera cualquier respuesta HTTP (no 000)
  local url="$1" timeout="${2:-45}" elapsed=0
  while (( elapsed < timeout )); do
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 2 "$url" 2>/dev/null || true)"
    if [[ "$code" != "000" ]]; then
      return 0
    fi
    sleep 1; elapsed=$((elapsed + 1))
  done
  return 1
}

port_tcp_in_use() { ss -tlnH "sport = :$1" 2>/dev/null | grep -q .; }
port_udp_in_use() { ss -lunH "sport = :$1" 2>/dev/null | grep -q .; }

cleanup() {
  trap - INT TERM EXIT
  echo
  log "Deteniendo procesos del stack…"
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] || continue
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  # Espera corta y luego fuerza SIGKILL a los que sigan vivos
  sleep 2
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] || continue
    kill -KILL -- "-$pid" 2>/dev/null || true
  done
  wait "${PIDS[@]:-}" 2>/dev/null || true
  if (( STOP_DB )); then
    log "Deteniendo contenedor PostgreSQL…"
    dc stop db >/dev/null 2>&1 || true
  elif (( DB_STARTED )); then
    log "PostgreSQL sigue arriba (docker compose). Detenerlo: docker compose -f $BACKEND_DIR/docker-compose.yml down"
  fi
  log "Stack detenido."
}
trap cleanup INT TERM EXIT

# ----------------------------------------------------------------------------
# 0. Preflight
# ----------------------------------------------------------------------------

log "Verificando prerrequisitos…"

command -v docker >/dev/null 2>&1 || die "docker no está instalado o no está en PATH."
((${#DC[@]})) || die "ni 'docker compose' ni 'docker-compose' están disponibles."
command -v npm >/dev/null 2>&1 || die "npm no está instalado o no está en PATH."
[[ -x "$VENV_DIR/bin/uvicorn" ]] || die "No existe $VENV_DIR/bin/uvicorn — crea el venv e instala requirements.txt."
[[ -x "$VENV_DIR/bin/alembic" ]] || die "No existe $VENV_DIR/bin/alembic — instala requirements.txt en el venv."
[[ -f "$BACKEND_DIR/.env" ]] || warn "Falta $BACKEND_DIR/.env — el backend usará defaults de config.py (revisa DATABASE_URL/SECRET_KEY)."
[[ -d "$FRONTEND_DIR/node_modules" ]] || die "Falta node_modules en drones-frontend — corre 'npm install' primero."

if (( WITH_SITL )) && [[ ! -x "$SITL_BIN" ]]; then
  warn "No existe el binario SITL en $SITL_BIN"
  warn "Instálalo con: $VENV_DIR/bin/pip install dronekit-sitl mavproxy"
  warn "Continuando de todos modos — el resto del stack funcionará sin dron simulado."
  WITH_SITL=0
fi

# ----------------------------------------------------------------------------
# 1. PostgreSQL + migraciones
# ----------------------------------------------------------------------------

if port_tcp_in_use 5432; then
  log "PostgreSQL ya responde en :5432 (instancia local o contenedor previo) — se omite docker compose."
else
  log "Levantando PostgreSQL (docker compose)…"
  dc up -d db >/dev/null
  DB_STARTED=1

  log "Esperando a que PostgreSQL acepte conexiones…"
  db_ready=0
  for _ in $(seq 1 30); do
    if dc exec -T db pg_isready -U drone_user -d drone_db >/dev/null 2>&1; then
      db_ready=1
      break
    fi
    sleep 1
  done
  (( db_ready )) || die "PostgreSQL no respondió en 30 s — revisa 'docker compose -f $BACKEND_DIR/docker-compose.yml logs db'."
fi

log "Aplicando migraciones Alembic…"
( cd "$BACKEND_DIR" && "$VENV_DIR/bin/alembic" upgrade head )

if (( BOOTSTRAP_ADMIN )); then
  log "Creando administrador inicial (interactivo)…"
  ( cd "$BACKEND_DIR" && "$VENV_DIR/bin/python" -m app.bootstrap_admin ) || \
    warn "Bootstrap de admin omitido (¿ya existe un administrador?)."
fi

# ----------------------------------------------------------------------------
# 2. SITL + MAVProxy (simulación del dron)
# ----------------------------------------------------------------------------

if (( WITH_SITL )); then
  if port_tcp_in_use 5760; then
    log "tcp:5760 ya en uso — se asume SITL corriendo, se omite su arranque."
  else
    launch "sitl" "$BACKEND_DIR" bash scripts/run_sitl.sh
    log "Esperando a que SITL quede escuchando en tcp:127.0.0.1:5760…"
    sleep 5
  fi

  if port_udp_in_use 14550; then
    log "udp:14550 ya ocupado — se asume relay MAVLink activo, se omite MAVProxy."
  elif (( WITH_GUI )); then
    launch "mavproxy" "$BACKEND_DIR" bash scripts/run_mavproxy.sh
    sleep 3
  else
    launch "mavproxy" "$BACKEND_DIR" \
      "$VENV_DIR/bin/mavproxy.py" --master tcp:127.0.0.1:5760 --out udp:127.0.0.1:14550
    sleep 3
  fi
else
  log "Modo --no-sitl: se omite el simulador. La API funcionará pero /drone/* responderá 503."
fi

# ----------------------------------------------------------------------------
# 3. Backend FastAPI
# ----------------------------------------------------------------------------

if wait_http "http://localhost:8000/api/v1/" 2; then
  log "La API ya responde en :8000 — se omite uvicorn."
else
  launch "backend" "$BACKEND_DIR" "$VENV_DIR/bin/uvicorn" app.main:app --reload

  log "Esperando a la API en http://localhost:8000/api/v1/ …"
  if ! wait_http "http://localhost:8000/api/v1/" 45; then
    die "La API no respondió en 45 s — revisa drones-backend/scripts/logs/backend.log"
  fi
fi

# ----------------------------------------------------------------------------
# 4. Frontend Vite
# ----------------------------------------------------------------------------

if wait_http "http://localhost:5173/" 2; then
  log "Vite ya responde en :5173 — se omite npm run dev."
  vite_url="http://localhost:5173"
else
  launch "frontend" "$FRONTEND_DIR" npm run dev

  if wait_http "http://localhost:5173/" 30; then
    vite_url="http://localhost:5173"
  else
    vite_url="(Vite tardó en responder — revisa drones-backend/scripts/logs/frontend.log)"
  fi
fi

# ----------------------------------------------------------------------------
# 5. Resumen y espera
# ----------------------------------------------------------------------------

cat <<EOF

============================================================================
  Stack AeroLuferan en ejecución
============================================================================
  Frontend   : $vite_url
  API        : http://localhost:8000/api/v1
  Swagger    : http://localhost:8000/docs
  MJPEG      : http://localhost:8000/api/v1/video/live
  Telemetría : ws://localhost:8000/api/v1/video/ws/telemetry
  Postgres   : localhost:5432 (instancia local o docker, sigue arriba al salir)
$(
  if (( WITH_SITL )); then
    echo "  SITL       : tcp:127.0.0.1:5760 → MAVProxy → udp:127.0.0.1:14550"
  else
    echo "  SITL       : omitido (--no-sitl)"
  fi
)
----------------------------------------------------------------------------
  Flujo demo sugerido (ver drones-backend/docs/E2E_DEMO.md):
    login admin → conectar dron (badge "Sin Señal" en Rutas)
    → programar misión con waypoints dentro de geocerca
    → Iniciar Vuelo → telemetría + video en En Vivo
    → POST /api/v1/detections/ingest para disparar una alerta
    → revisar Alertas → RTL / Cancelar → Bitácora

  Video MJPEG simulado (terminal aparte, desde drones-backend/):
    DRONE_API_TOKEN=<jwt> venv/bin/python scripts/run_camera_stream.py \\
        --source synthetic --fps 10

  Ctrl+C para detener todo (Postgres queda arriba salvo --stop-db).
============================================================================
EOF

# Mantener el script vivo mientras haya hijos; si alguno muere, avisar.
if ((${#PIDS[@]} == 0)); then
  log "Todos los servicios ya estaban activos — nada que supervisar."
  log "Tip: para que este script gestione los procesos, detén primero los que corren por su cuenta."
  exit 0
fi

while ((${#PIDS[@]})); do
  alive=()
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      alive+=("$pid")
    else
      warn "El proceso '${PID_NAMES[$pid]:-?}' (pid $pid) terminó — revisa drones-backend/scripts/logs/${PID_NAMES[$pid]:-servicio}.log"
    fi
  done
  PIDS=("${alive[@]}")
  sleep 3
done
warn "Todos los procesos terminaron."
exit 1
