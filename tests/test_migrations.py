from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from api.db import ALEMBIC_INI, Base, engine


def test_migrations_produce_exactly_the_model_schema(client):
    """The client fixture built this database with the real migrations."""
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    for name, table in Base.metadata.tables.items():
        assert {c["name"] for c in inspector.get_columns(name)} == {c.name for c in table.columns}, name


def test_no_model_change_is_missing_a_migration(client):
    """Fails when someone edits api/models.py without generating a migration."""
    command.check(Config(str(ALEMBIC_INI)))
