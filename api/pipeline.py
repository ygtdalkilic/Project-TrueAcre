"""Run resolve -> reconcile -> score on one company's uploaded tables.

Results are cached per (company, data version), so a company's scores are recomputed only
after an upload. The cache is per server instance.
"""
import io
import threading

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import models
from api.crypto import decrypt
from api.tables import TABLES
from engine.reconcile import reconcile
from engine.resolve import resolve
from engine.score import score

_cache: dict[int, tuple[int, dict]] = {}
_lock = threading.Lock()


def load_tables(db: Session, org: models.Organization) -> dict[str, pd.DataFrame]:
    rows = db.scalars(select(models.Dataset).where(models.Dataset.org_id == org.id)).all()
    return {d.table_name: pd.read_csv(io.StringIO(decrypt(d.ciphertext))) for d in rows}


def forget(org_id: int) -> None:
    with _lock:
        _cache.pop(org_id, None)


def results(db: Session, org: models.Organization) -> dict:
    """{'tables', 'resolved', 'scores'} for the company, or 409 listing the tables still missing."""
    with _lock:
        cached = _cache.get(org.id)
        if cached and cached[0] == org.data_version:
            return cached[1]

    tables = load_tables(db, org)
    missing = [t for t in TABLES if t not in tables]
    if missing:
        raise HTTPException(status_code=409, detail={"message": "upload these tables first", "missing": missing})

    resolved = resolve(tables)
    scores = (
        score(reconcile(resolved))
        .merge(tables["growers"][["grower_id", "name"]], on="grower_id")
        .sort_values(["fair_play_score", "grower_id", "season"])
    )
    result = {"tables": tables, "resolved": resolved, "scores": scores}
    with _lock:
        _cache[org.id] = (org.data_version, result)
    return result
