"""Bring the database to the latest Alembic revision at app startup.

Dev databases created before Alembic existed (via create_all) have all the
tables but no alembic_version — running the initial migration against them
would fail on "table already exists". Those get stamped with the initial
revision instead of migrated, then upgraded normally from there.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.database.session import engine

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Revision that matches the schema create_all used to build; only valid as a
# stamp target while the pre-Alembic schema and this revision are identical.
INITIAL_REVISION = "c81848f6a4f9"


def run_migrations() -> None:
    cfg = Config(PROJECT_ROOT / "alembic.ini")
    inspector = inspect(engine)
    if inspector.has_table("users") and not inspector.has_table("alembic_version"):
        logger.info("pre-Alembic database detected; stamping revision %s", INITIAL_REVISION)
        command.stamp(cfg, INITIAL_REVISION)
    command.upgrade(cfg, "head")
