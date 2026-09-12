"""Database access.

DATABASE_URL selects the backend: a local SQLite file by default (development and tests),
Postgres in the cloud (postgresql+psycopg://...). Tables are created at startup; the schema is
small enough that there are no migrations yet.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DEFAULT_URL = "sqlite:///trueacre.db"  # file in the repo root; *.db is gitignored
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_URL)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from api import models  # noqa: F401  registers the tables on Base

    Base.metadata.create_all(engine)


def get_db():
    with SessionLocal() as db:
        yield db
