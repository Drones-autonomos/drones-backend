import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.api import api_router
from app.api.v1.endpoints.settings import hydrate_runtime_settings_from_db
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.setting import AjustesOperativos
from app.services.charging_base_service import charging_base_service
from app.services.mission_service import MissionError, mission_service
from app.services.purge_job import (
    scheduler,
    start_purge_scheduler,
)
from app.services.seed_service import ensure_roles_and_demo_users


def _bootstrap_runtime_state() -> bool:
    """Sincroniza roles, estaciones de carga y ventana normativa desde la BD real."""
    if str(settings.DATABASE_URL).startswith("sqlite:///:memory:"):
        return bool(settings.MISSION_SCHEDULER_ENABLED)
    db = SessionLocal()
    try:
        is_dev = os.getenv("ENVIRONMENT", "development").lower() in ("dev", "development", "local")
        seed_demo = os.getenv("SEED_DEMO_USERS", "true" if is_dev else "false").lower() == "true"
        ensure_roles_and_demo_users(db, seed_demo_users=seed_demo)
        charging_base_service.ensure_default_stations(db)
        hydrate_runtime_settings_from_db(db)
        row = db.query(AjustesOperativos).order_by(AjustesOperativos.id.asc()).first()
        persisted_scheduler = bool(getattr(row, "scheduler_enabled", False)) if row else False
        return bool(settings.MISSION_SCHEDULER_ENABLED or persisted_scheduler)
    except Exception:
        db.rollback()
        return bool(settings.MISSION_SCHEDULER_ENABLED)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    should_start_scheduler = _bootstrap_runtime_state()
    start_purge_scheduler()
    if should_start_scheduler:
        mission_service.start_scheduler()
    try:
        yield
    finally:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
        await asyncio.to_thread(mission_service.shutdown)


def _normalize_route_path(path: str | None) -> str | None:
    if path is None:
        return None
    cleaned = path.strip()
    if not cleaned:
        return None
    return cleaned if cleaned.startswith("/") else f"/{cleaned}"


app = FastAPI(
    lifespan=lifespan,
    title=settings.PROJECT_NAME,
    openapi_url=_normalize_route_path(getattr(settings, "OPENAPI_URL", None)) or "/openapi.json",
    docs_url=_normalize_route_path(getattr(settings, "DOCS_URL", None)) or "/docs",
    redoc_url=_normalize_route_path(getattr(settings, "REDOC_URL", None)) or "/redoc",
)

default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
extra_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
origins = list(dict.fromkeys([*default_origins, *extra_origins]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_prefix = (settings.API_V1_STR or "/api/v1").strip()
if not api_prefix.startswith("/"):
    api_prefix = f"/{api_prefix}"

app.include_router(api_router, prefix=api_prefix)


@app.get("/")
def root():
    return {"status": "ok", "message": "API Drones Autónomos activa"}


@app.exception_handler(MissionError)
async def mission_error_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})
