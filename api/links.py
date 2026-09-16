"""Human review of record links.

The resolver links external records to growers only when exactly one grower qualifies, and it
refuses the rest. This queue shows an analyst everything that deserves a human look: records the
resolver could not link, records it linked only by fuzzy name similarity, and past rulings. The
analyst picks the right grower from ranked candidates, or rules that a record matches nobody.
Rulings override the resolver and are recorded in the audit log.
"""
import difflib

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import audit, models
from api.auth import current_membership
from api.db import get_db
from api.pipeline import results
from engine.resolve import SOURCES, normalize_name

router = APIRouter(prefix="/api/links", tags=["links"])

NEEDS_CHECK = {"fuzzy name"}  # automatic link methods that get a second look
CANDIDATES = 5  # growers offered per record, best name similarity first
AMOUNT_COLUMN = {"acreage_reports": "acres", "elevator_receipts": "bushels"}


class Decision(BaseModel):
    record_id: str
    grower_id: str | None = None  # None: this record matches nobody
    note: str | None = None


def _candidates(name: str, county: str, growers, current: str | None) -> list[dict]:
    norm = normalize_name(name)
    local = growers[growers["county"] == county]
    ranked = sorted(
        ({"grower_id": g.grower_id, "name": g.name,
          "similarity": round(difflib.SequenceMatcher(None, norm, normalize_name(g.name)).ratio(), 2)}
         for g in local.itertuples()),
        key=lambda c: (c["grower_id"] != current, -c["similarity"]),
    )
    return ranked[:CANDIDATES]


@router.get("/review")
def review(membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)) -> list[dict]:
    res = results(db, membership.organization)
    tables, resolved = res["tables"], res["resolved"]
    decisions = {d.record_id: d for d in db.scalars(
        select(models.LinkDecision).where(models.LinkDecision.org_id == membership.org_id))}
    unmatched = resolved["unmatched"].set_index("record_id")
    growers = tables["growers"]

    items = []
    for table, name_col, _farm_col, id_col in SOURCES:
        automatic = resolved[table].set_index(id_col)
        for rec in tables[table].itertuples():
            record_id = getattr(rec, id_col)
            name, county = getattr(rec, name_col), rec.county
            if record_id in decisions:
                d = decisions[record_id]
                status, grower_id, reason = "analyst", d.grower_id, d.note
            elif record_id in unmatched.index:
                status, grower_id, reason = "unmatched", None, unmatched.loc[record_id, "reason"]
            elif record_id in automatic.index and automatic.loc[record_id, "match_method"] in NEEDS_CHECK:
                status, grower_id, reason = "check", automatic.loc[record_id, "grower_id"], automatic.loc[record_id, "match_method"]
            else:
                continue  # confidently linked by farm number or exact name: nothing to review
            items.append({
                "source": table, "record_id": record_id, "name": name, "county": county,
                "season": int(rec.season), "amount": float(getattr(rec, AMOUNT_COLUMN[table])),
                "status": status, "grower_id": grower_id, "reason": reason,
                "candidates": _candidates(name, county, growers, grower_id),
            })
    order = {"unmatched": 0, "check": 1, "analyst": 2}
    return sorted(items, key=lambda i: (order[i["status"]], i["source"], i["record_id"]))


@router.post("/decisions", status_code=201)
def decide(body: Decision, request: Request, membership: models.Membership = Depends(current_membership),
           db: Session = Depends(get_db)) -> dict:
    tables = results(db, membership.organization)["tables"]
    known_records = set().union(*(set(tables[t][id_col]) for t, _n, _f, id_col in SOURCES))
    if body.record_id not in known_records:
        raise HTTPException(status_code=404, detail="no such acreage report or elevator receipt")
    if body.grower_id is not None and body.grower_id not in set(tables["growers"]["grower_id"]):
        raise HTTPException(status_code=404, detail="no such grower")

    decision = db.scalar(select(models.LinkDecision).where(models.LinkDecision.org_id == membership.org_id,
                                                           models.LinkDecision.record_id == body.record_id))
    if decision is None:
        decision = models.LinkDecision(org_id=membership.org_id, record_id=body.record_id)
        db.add(decision)
    decision.grower_id, decision.note, decision.decided_by = body.grower_id, body.note, membership.user_id
    membership.organization.data_version += 1
    audit.record(db, "link.decide", request=request, user_id=membership.user_id, org_id=membership.org_id,
                 record_id=body.record_id, grower_id=body.grower_id)
    db.commit()
    return {"record_id": body.record_id, "grower_id": body.grower_id}


@router.delete("/decisions/{record_id}", status_code=204)
def revert(record_id: str, request: Request, membership: models.Membership = Depends(current_membership),
           db: Session = Depends(get_db)):
    decision = db.scalar(select(models.LinkDecision).where(models.LinkDecision.org_id == membership.org_id,
                                                           models.LinkDecision.record_id == record_id))
    if decision is None:
        raise HTTPException(status_code=404, detail="no decision for that record")
    db.delete(decision)
    membership.organization.data_version += 1
    audit.record(db, "link.revert", request=request, user_id=membership.user_id, org_id=membership.org_id,
                 record_id=record_id)
    db.commit()
