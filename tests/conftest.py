"""Test environment: a throwaway SQLite database, dev login on, no Google client, no LLM provider.

Set before api.main is imported anywhere, which is why this lives in conftest.
"""
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["TRUEACRE_ENV"] = "development"
os.environ["TRUEACRE_DEV_LOGIN"] = "1"
os.environ["SESSION_SECRET"] = "test-secret"
for var in ("GOOGLE_CLIENT_ID", "TRUEACRE_LLM_PROVIDER", "TRUEACRE_ALLOWED_HOSTS"):
    os.environ.pop(var, None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sqlalchemy import text  # noqa: E402

from api import auth, datasets, scores  # noqa: E402
from api.db import Base, engine, init_db  # noqa: E402
from api.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Every test shares one client IP, so limits would otherwise carry over between tests."""
    for limiter in (auth.LOGIN_LIMIT, datasets.UPLOAD_LIMIT, scores.EXPLAIN_LIMIT):
        limiter._events.clear()


@pytest.fixture
def client():
    """A fresh, empty database for every test, built by the real migrations, so tests cannot depend
    on each other's users or companies and the migrations are exercised on every run."""
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    init_db()
    with TestClient(app) as c:
        yield c


def login(client: TestClient, email: str, name: str = "") -> dict:
    response = client.post("/api/auth/dev", json={"email": email, "name": name})
    assert response.status_code == 200, response.text
    return response.json()


def create_org(client: TestClient, name: str) -> dict:
    response = client.post("/api/orgs", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def load_demo(client: TestClient) -> None:
    response = client.post("/api/data/demo")
    assert response.status_code == 200, response.text
