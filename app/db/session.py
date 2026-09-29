from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# Normaliza el scheme a postgresql+psycopg2 para que SQLAlchemy 2.x
# use psycopg2-binary independientemente de cómo esté definida DATABASE_URL.
_db_url = settings.DATABASE_URL.replace(
    "postgresql://", "postgresql+psycopg2://", 1
)

engine = create_engine(_db_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
