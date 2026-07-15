"""Schema-drift guard: the migration chain must fully describe the models.

Importing the app (conftest) runs `upgrade head` on the test database, so an
empty autogenerate diff here proves models.py and migrations/versions agree.
Fails whenever someone edits a model without `alembic revision --autogenerate`.
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.database.models import Base
from app.database.session import engine


def test_migrations_match_models(client):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], f"models.py changed without a migration: {diff}"
