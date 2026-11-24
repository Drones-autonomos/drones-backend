import logging
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.recording import Grabacion

logger = logging.getLogger("purge_job")

scheduler = BackgroundScheduler()


def purge_expired_recordings(db: Session | None = None) -> int:
    """Elimina los archivos físicos .enc vencidos conservando el registro y su hash SHA-256."""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        now = datetime.utcnow()
        expiradas = (
            session.query(Grabacion)
            .filter(
                Grabacion.purgado == False,  # noqa: E712
                Grabacion.fecha_purga <= now,
            )
            .all()
        )
        purgadas_count = 0

        for grabacion in expiradas:
            if grabacion.ruta_archivo and os.path.exists(grabacion.ruta_archivo):
                try:
                    os.remove(grabacion.ruta_archivo)
                except OSError as e:
                    logger.error(f"Error borrando archivo físico {grabacion.ruta_archivo}: {e}")

            grabacion.purgado = True
            purgadas_count += 1

        session.commit()
        if purgadas_count > 0:
            logger.info(
                f"Purga normativa completada: {purgadas_count} archivos eliminados conservando sello SHA-256."
            )
        return purgadas_count
    except Exception as e:
        session.rollback()
        logger.error(f"Error en job de purga: {e}")
        return 0
    finally:
        if owns_session:
            session.close()


def start_purge_scheduler():
    global scheduler
    if scheduler is None or getattr(scheduler, "state", 0) == 0:
        scheduler = BackgroundScheduler()
    if not scheduler.running:
        scheduler.add_job(
            purge_expired_recordings,
            "cron",
            hour=0,
            minute=0,
            id="purge_expired_recordings_job",
            replace_existing=True,
        )
        scheduler.start()


def stop_purge_scheduler():
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
