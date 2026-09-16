"""Run resolve -> analyst decisions -> reconcile -> score on one company's uploaded tables.

Results are cached per (company, data version). Uploads and link decisions bump the version,
so scores are recomputed only when something changed. The cache is per server instance.
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
from engine.resolve import SOURCES, resolve
from engine.score import score

_cache: dict[int, tuple[int, dict]] = {}
_lock = threading.Lock()


def load_tables(db: Session, org: models.Organization) -> dict[str, pd.DataFrame]:
    rows = db.scalars(select(models.Dataset).where(models.Dataset.org_id == org.id)).all()
    return {d.table_name: pd.read_csv(io.StringIO(decrypt(d.ciphertext))) for d in rows}


def load_decisions(db: Session, org_id: int) -> dict[str, str | None]:
    """record_id -> grower_id (None = analyst ruled it matches nobody)."""
    return {d.record_id: d.grower_id
            for d in db.scalars(select(models.LinkDecision).where(models.LinkDecision.org_id == org_id))}


def apply_decisions(resolved: dict[str, pd.DataFrame], tables: dict[str, pd.DataFrame],
                    decisions: dict[str, str | None]) -> dict[str, pd.DataFrame]:
    """Override the automatic resolver with analyst rulings. Pure function.

    A decided record leaves both the automatic links and the unmatched list. If the ruling names a
    grower, the record comes back linked to that grower with match_method 'analyst'.
    """
    if not decisions:
        return resolved
    out = dict(resolved)
    linked = {r: g for r, g in decisions.items() if g is not None}
    for table, _name_col, _farm_col, id_col in SOURCES:
        automatic = resolved[table]
        kept = automatic[~automatic[id_col].isin(decisions)]
        manual = tables[table][tables[table][id_col].isin(linked)].copy()
        manual["grower_id"] = manual[id_col].map(linked)
        manual["match_method"] = "analyst"
        out[table] = pd.concat([kept, manual], ignore_index=True)
    unmatched = resolved["unmatched"]
    out["unmatched"] = unmatched[~unmatched["record_id"].isin(decisions)].reset_index(drop=True)
    return out


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

    resolved = apply_decisions(resolve(tables), tables, load_decisions(db, org.id))
    scores = (
        score(reconcile(resolved))
        .merge(tables["growers"][["grower_id", "name"]], on="grower_id")
        .sort_values(["fair_play_score", "grower_id", "season", "crop"])
    )
    result = {"tables": tables, "resolved": resolved, "scores": scores}
    with _lock:
        _cache[org.id] = (org.data_version, result)
    return result


def forget(org_id: int) -> None:
    with _lock:
        _cache.pop(org_id, None)
