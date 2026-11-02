"""The grower's own view: their seasons, the evidence behind each score, and their seed statement.

A grower member is linked to exactly one grower record, and every route here is scoped to it. Staff
routes refuse the grower role (api.auth.current_membership), so nothing else in the company is
reachable. Dealer coverage, the names of non-reporting dealers, and the replant signal stay
staff-only: the first two would show a grower where purchases go unseen.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import audit, models
from api.auth import current_grower
from api.db import get_db
from api.pipeline import results
from api.scores import _evidence, _records

router = APIRouter(prefix="/api/grower", tags=["grower"])

GROWER_COLUMNS = [  # what a grower sees of their own score row
    "grower_id", "name", "county", "state", "season", "crop", "fair_play_score", "label",
    "gap_fraction", "unsupported_acre_fraction", "unsupported_bushel_fraction",
    "licensed_acres", "other_seed_acres", "declared_acres", "delivered_bushels", "yield_ceiling", "max_bushels",
    "acre_gap", "bushel_gap", "has_purchases", "has_acreage", "has_deliveries", "has_statement",
]


class Statement(BaseModel):
    other_seed_acres: float = Field(ge=0, allow_inf_nan=False)


def _mine(db: Session, m: models.Membership):
    scores = results(db, m.organization)["scores"]
    return scores[scores["grower_id"] == m.grower_id]


@router.get("/seasons")
def my_seasons(m: models.Membership = Depends(current_grower), db: Session = Depends(get_db)) -> list[dict]:
    return _records(_mine(db, m).sort_values(["season", "crop"])[GROWER_COLUMNS])


@router.get("/seasons/{season}/crops/{crop}")
def my_evidence(season: int, crop: str, request: Request, m: models.Membership = Depends(current_grower),
                db: Session = Depends(get_db)) -> dict:
    evidence = _evidence(results(db, m.organization), m.grower_id, season, crop)
    evidence["score"] = {k: v for k, v in evidence["score"].items() if k in GROWER_COLUMNS}
    evidence["clear"] = {**evidence["clear"], "non_reporting_dealers": []}
    audit.record(db, "grower.evidence_view", request=request, user_id=m.user_id, org_id=m.org_id,
                 grower_id=m.grower_id, season=season, crop=crop)
    db.commit()
    return evidence


@router.put("/seasons/{season}/crops/{crop}/statement")
def file_statement(season: int, crop: str, body: Statement, request: Request,
                   m: models.Membership = Depends(current_grower), db: Session = Depends(get_db)) -> dict:
    """The grower states how many acres of this crop they planted this season with seed not bought from
    this company. It replaces any uploaded statement for the same season and crop."""
    mine = _mine(db, m)
    if not ((mine["season"] == season) & (mine["crop"] == crop)).any():
        raise HTTPException(status_code=404, detail="no record of that season and crop for you")
    statement = db.scalar(select(models.GrowerStatement).where(
        models.GrowerStatement.org_id == m.org_id, models.GrowerStatement.grower_id == m.grower_id,
        models.GrowerStatement.season == season, models.GrowerStatement.crop == crop))
    if statement is None:
        statement = models.GrowerStatement(org_id=m.org_id, grower_id=m.grower_id, season=season, crop=crop,
                                           other_seed_acres=0.0)
        db.add(statement)
    statement.other_seed_acres = body.other_seed_acres
    statement.submitted_by, statement.submitted_at = m.user_id, datetime.now(timezone.utc)
    m.organization.data_version += 1
    audit.record(db, "grower.statement", request=request, user_id=m.user_id, org_id=m.org_id,
                 grower_id=m.grower_id, season=season, crop=crop, other_seed_acres=body.other_seed_acres)
    db.commit()
    return {"season": season, "crop": crop, "other_seed_acres": body.other_seed_acres}
