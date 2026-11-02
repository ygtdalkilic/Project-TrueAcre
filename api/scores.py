"""Scores, per-grower evidence, unmatched records, and optional explanations, scoped to the
signed-in user's company. Every score is per grower, season, and crop."""
import httpx
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api import audit, models
from api.auth import current_membership
from api.db import get_db
from api.pipeline import results
from api.security import RateLimiter
from engine.clear import what_would_clear
from engine.explain import ExplainError, LLMClient, explain
from engine.reconcile import YIELD_SIGMAS

router = APIRouter(prefix="/api", tags=["scores"])

# Explanations call a chat model, cloud or local; off unless a provider is configured. The dashboard hides the button.
EXPLAIN_CLIENT = LLMClient.from_env()
EXPLAIN_LIMIT = RateLimiter(limit=20, window_seconds=60)  # per company; these calls can cost money

SCORE_COLUMNS = [
    "grower_id", "name", "county", "state", "season", "crop", "fair_play_score", "label",
    "gap_fraction", "unsupported_acre_fraction", "unsupported_bushel_fraction", "coverage",
    "licensed_acres", "other_seed_acres", "declared_acres", "delivered_bushels", "yield_ceiling", "max_bushels",
    "acre_gap", "bushel_gap", "has_purchases", "has_acreage", "has_deliveries", "has_statement",
    "explained_share", "replant_signal", "replant_from_season",
]
HISTORY_COLUMNS = ["season", "declared_acres", "licensed_acres", "other_seed_acres", "explained_share", "label"]


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame rows as JSON-safe dicts (NaN becomes null)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


@router.get("/scores")
def list_scores(season: int | None = None, county: str | None = None, label: str | None = None,
                crop: str | None = None, membership: models.Membership = Depends(current_membership),
                db: Session = Depends(get_db)) -> list[dict]:
    df = results(db, membership.organization)["scores"]
    for column, value in (("season", season), ("county", county), ("label", label), ("crop", crop)):
        if value is not None:
            df = df[df[column] == value]
    return _records(df[SCORE_COLUMNS])


def _evidence(res: dict, grower_id: str, season: int, crop: str) -> dict:
    scores, tables, resolved = res["scores"], res["tables"], res["resolved"]
    match = scores[(scores["grower_id"] == grower_id) & (scores["season"] == season) & (scores["crop"] == crop)]
    if match.empty:
        raise HTTPException(status_code=404, detail="no data for that grower, season, and crop")
    row = match.iloc[0]

    purchases = tables["seed_purchases"]
    purchases = purchases[(purchases["grower_id"] == grower_id) & (purchases["season"] == season)]
    purchases = purchases.merge(tables["dealers"][["dealer_id", "name"]].rename(columns={"name": "dealer"}), on="dealer_id")
    purchases = purchases.merge(tables["varieties"], on="variety_id")
    purchases = purchases[purchases["crop"] == crop]
    purchases["acres_supported"] = purchases["units"] * purchases["seeds_per_unit"] / purchases["target_seeds_per_acre"]

    def own(df):
        return df[(df["grower_id"] == grower_id) & (df["season"] == season) & (df["crop"] == crop)]

    acreage, receipts = own(resolved["acreage_reports"]), own(resolved["elevator_receipts"])
    yields = tables["county_yields"]
    yields = yields[(yields["county"] == row["county"]) & (yields["state"] == row["state"])
                    & (yields["season"] == season) & (yields["crop"] == crop)]
    history = scores[(scores["grower_id"] == grower_id) & (scores["crop"] == crop)].sort_values("season")

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
        "clear": what_would_clear(row, purchases.rename(columns={"name": "variety"}), tables["dealers"]),
        "history": _records(history[HISTORY_COLUMNS]),
    }


@router.get("/growers/{grower_id}/seasons/{season}/crops/{crop}")
def grower_evidence(grower_id: str, season: int, crop: str, request: Request,
                    membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)) -> dict:
    evidence = _evidence(results(db, membership.organization), grower_id, season, crop)
    audit.record(db, "evidence.view", request=request, user_id=membership.user_id, org_id=membership.org_id,
                 grower_id=grower_id, season=season, crop=crop)
    db.commit()
    return evidence


@router.get("/unmatched")
def list_unmatched(membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)) -> list[dict]:
    """External records that could not be linked to exactly one registered grower. Excluded from every score."""
    return _records(results(db, membership.organization)["resolved"]["unmatched"])


@router.post("/growers/{grower_id}/seasons/{season}/crops/{crop}/explanation")
def grower_explanation(grower_id: str, season: int, crop: str, request: Request,
                       membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)) -> dict:
    """Plain-English reading of the evidence, written by the configured chat model. Never changes the score."""
    if EXPLAIN_CLIENT is None:
        raise HTTPException(status_code=503, detail="explanations are disabled; set TRUEACRE_LLM_PROVIDER to enable them")
    EXPLAIN_LIMIT.check(str(membership.org_id))
    evidence = _evidence(results(db, membership.organization), grower_id, season, crop)
    audit.record(db, "explanation.request", request=request, user_id=membership.user_id, org_id=membership.org_id,
                 grower_id=grower_id, season=season, crop=crop, provider=EXPLAIN_CLIENT.provider)
    db.commit()
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
