import logging
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.db.session import SessionLocal
from app.models.recording import Grabacion

logger = logging.getLogger("purge_job")

scheduler = BackgroundScheduler()


def purge_expired_recordings():
    """Busca y elimina grabaciones con fecha_purga vencida."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        expiradas = db.query(Grabacion).filter(Grabacion.fecha_purga <= now).all()
        eliminadas_count = 0

        for grabacion in expiradas:
            if os.path.exists(grabacion.ruta_archivo):
                try:
                    os.remove(grabacion.ruta_archivo)
                except OSError as e:
                    logger.error(f"Error borrando archivo físico {grabacion.ruta_archivo}: {e}")

            db.delete(grabacion)
            eliminadas_count += 1

        db.commit()
        if eliminadas_count > 0:
            logger.info(f"Purga exitosa: {eliminadas_count} grabaciones eliminadas a los 30 días.")
    except Exception as e:
        logger.error(f"Error en job de purga: {e}")
    finally:
        db.close()


def start_purge_scheduler():
    scheduler = BackgroundScheduler()
    # Programado para correr cada 24 horas (o cada medianoche)
    scheduler.add_job(purge_expired_recordings, "cron", hour=0, minute=0)
    scheduler.start()
