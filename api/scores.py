"""Scores, per-grower evidence, unmatched records, and optional explanations, scoped to the
signed-in user's company."""
import httpx
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api import models
from api.auth import current_membership
from api.db import get_db
from api.pipeline import results
from api.security import RateLimiter
from engine.explain import ExplainError, LLMClient, explain
from engine.reconcile import YIELD_SIGMAS

router = APIRouter(prefix="/api", tags=["scores"])

# Explanations call a chat model, cloud or local; off unless a provider is configured. The dashboard hides the button.
EXPLAIN_CLIENT = LLMClient.from_env()
EXPLAIN_LIMIT = RateLimiter(limit=20, window_seconds=60)  # per company; these calls can cost money

SCORE_COLUMNS = [
    "grower_id", "name", "county", "state", "season", "fair_play_score", "label",
    "gap_fraction", "unsupported_acre_fraction", "unsupported_bushel_fraction", "coverage",
    "licensed_acres", "declared_acres", "delivered_bushels", "yield_ceiling", "max_bushels",
    "acre_gap", "bushel_gap", "has_purchases", "has_acreage", "has_deliveries",
]


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame rows as JSON-safe dicts (NaN becomes null)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


@router.get("/scores")
def list_scores(season: int | None = None, county: str | None = None, label: str | None = None,
                membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)) -> list[dict]:
    df = results(db, membership.organization)["scores"]
    if season is not None:
        df = df[df["season"] == season]
    if county is not None:
        df = df[df["county"] == county]
    if label is not None:
        df = df[df["label"] == label]
    return _records(df[SCORE_COLUMNS])


@router.get("/growers/{grower_id}/seasons/{season}")
def grower_evidence(grower_id: str, season: int, membership: models.Membership = Depends(current_membership),
                    db: Session = Depends(get_db)) -> dict:
    res = results(db, membership.organization)
    scores, tables, resolved = res["scores"], res["tables"], res["resolved"]
    match = scores[(scores["grower_id"] == grower_id) & (scores["season"] == season)]
    if match.empty:
        raise HTTPException(status_code=404, detail="no data for that grower and season")
    row = match.iloc[0]

    purchases = tables["seed_purchases"]
    purchases = purchases[(purchases["grower_id"] == grower_id) & (purchases["season"] == season)]
    purchases = purchases.merge(tables["dealers"][["dealer_id", "name"]].rename(columns={"name": "dealer"}), on="dealer_id")
    purchases = purchases.merge(tables["varieties"], on="variety_id")
    purchases["acres_supported"] = purchases["units"] * purchases["seeds_per_unit"] / purchases["target_seeds_per_acre"]

    acreage = resolved["acreage_reports"]
    acreage = acreage[(acreage["grower_id"] == grower_id) & (acreage["season"] == season)]
    receipts = resolved["elevator_receipts"]
    receipts = receipts[(receipts["grower_id"] == grower_id) & (receipts["season"] == season)]
    yields = tables["county_yields"]
    yields = yields[(yields["county"] == row["county"]) & (yields["season"] == season)]

    return {
        "score": _records(match[SCORE_COLUMNS])[0],
        "purchases": _records(purchases[[
            "purchase_id", "dealer", "variety_id", "name", "units", "seeds_per_unit",
            "target_seeds_per_acre", "acres_supported",
        ]].rename(columns={"name": "variety"})),
        "acreage_reports": _records(acreage[["report_id", "operator_name", "farm_number", "match_method", "crop", "acres"]]),
        "elevator_receipts": _records(receipts[["receipt_id", "seller_name", "elevator_id", "match_method", "crop", "bushels"]]),
        "county_yield": _records(yields[["county", "state", "mean_yield", "std_yield"]])[0] if not yields.empty else None,
        "yield_sigmas": YIELD_SIGMAS,
    }


@router.get("/unmatched")
def list_unmatched(membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)) -> list[dict]:
    """External records that could not be linked to exactly one registered grower. Excluded from every score."""
    return _records(results(db, membership.organization)["resolved"]["unmatched"])


@router.post("/growers/{grower_id}/seasons/{season}/explanation")
def grower_explanation(grower_id: str, season: int, membership: models.Membership = Depends(current_membership),
                       db: Session = Depends(get_db)) -> dict:
    """Plain-English reading of the evidence, written by the configured chat model. Never changes the score."""
    if EXPLAIN_CLIENT is None:
        raise HTTPException(status_code=503, detail="explanations are disabled; set TRUEACRE_LLM_PROVIDER to enable them")
    EXPLAIN_LIMIT.check(str(membership.org_id))
    evidence = grower_evidence(grower_id, season, membership, db)
    try:
        return {"explanation": explain(evidence, EXPLAIN_CLIENT)}
    except ExplainError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"{EXPLAIN_CLIENT.provider} returned {e.response.status_code}: {e.response.text[:300]}",
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"could not reach {EXPLAIN_CLIENT.provider} at {EXPLAIN_CLIENT.base_url}: {e}")
