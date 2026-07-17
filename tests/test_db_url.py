"""DATABASE_URL normalization: Neon-style URLs get the psycopg driver pinned."""

from app.core.config import settings
from app.database.session import sqlalchemy_url


def test_postgres_urls_pinned_to_psycopg(monkeypatch):
    for raw in (
        "postgres://u:p@host.neon.tech/db?sslmode=require",
        "postgresql://u:p@host.neon.tech/db?sslmode=require",
    ):
        monkeypatch.setattr(settings, "database_url", raw)
        assert sqlalchemy_url() == "postgresql+psycopg://u:p@host.neon.tech/db?sslmode=require"


def test_sqlite_url_untouched(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "sqlite:///./dev.db")
    assert sqlalchemy_url() == "sqlite:///./dev.db"
