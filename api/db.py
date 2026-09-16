"""Database access.

DATABASE_URL selects the backend: a local SQLite file by default (development and tests),
Postgres in the cloud (postgresql+psycopg://...). The schema is managed by Alembic migrations in
migrations/; init_db() upgrades to the latest one at startup, so a deploy that adds a table or
column applies it before serving traffic.
"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DEFAULT_URL = "sqlite:///trueacre.db"  # file in the repo root; *.db is gitignored
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_URL)
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Apply any pending migrations."""
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(ALEMBIC_INI)), "head")


def get_db():
    with SessionLocal() as db:
        yield db
