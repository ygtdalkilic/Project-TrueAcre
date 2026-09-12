"""TrueAcre API and, in production, the dashboard.

Every route lives under /api. When web/dist exists (the production container), the built
dashboard is served from / by this same process, so there is no CORS and one URL to deploy.

Configuration (environment variables, all optional unless noted):
  DATABASE_URL            SQLite file by default; Postgres in the cloud (see api/db.py)
  GOOGLE_CLIENT_ID        enables Google sign-in (see api/auth.py)
  SESSION_SECRET          signs session cookies; required in production
  TRUEACRE_ENV            "production" turns on HSTS, Secure cookies, and disables dev login and API docs
  TRUEACRE_DEV_LOGIN      "1" enables email-only login outside production
  TRUEACRE_ALLOWED_HOSTS  comma-separated Host values the server answers to (default: any)
  TRUEACRE_LLM_PROVIDER   enables plain-English explanations (see engine/explain.py)

Put secrets in a gitignored .env and start with: uvicorn api.main:app --reload --env-file .env
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api import auth, datasets, orgs, scores
from api.db import init_db
from api.security import IS_PRODUCTION, SameOriginMiddleware, SecurityHeadersMiddleware

ALLOWED_HOSTS = os.environ.get("TRUEACRE_ALLOWED_HOSTS", "*").split(",")
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="TrueAcre",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/api/docs",
    redoc_url=None,
    openapi_url=None if IS_PRODUCTION else "/api/openapi.json",
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SameOriginMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

for module in (auth, orgs, datasets, scores):
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/config")
def config() -> dict:
    """Public settings the dashboard needs before anyone is signed in."""
    client = scores.EXPLAIN_CLIENT
    return {
        "google_client_id": auth.GOOGLE_CLIENT_ID,
        "dev_login": auth.DEV_LOGIN,
        "explanations_enabled": client is not None,
        "provider": client.provider if client else None,
        "model": client.model if client else None,
    }


if WEB_DIST.is_dir():
    # The dashboard has no client-side routes, so plain static serving is enough: index.html at /,
    # the built assets, and the legal pages. API routes above take precedence; anything else is 404.
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
