from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def sqlalchemy_url() -> str:
    """Normalize DATABASE_URL for SQLAlchemy.

    Neon/Heroku hand out postgres:// or postgresql:// URLs; without an
    explicit driver SQLAlchemy would reach for psycopg2. We ship psycopg
    (v3), so pin the dialect to it.
    """
    url = settings.database_url
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


# pool_pre_ping: Neon's free tier autosuspends after idle minutes, killing
# pooled connections; the ping replaces the dead ones transparently.
engine = create_engine(sqlalchemy_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
