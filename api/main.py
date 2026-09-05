"""FastAPI endpoints: scored grower-seasons and the evidence behind each one.

Configuration (environment variables, all optional):
  TRUEACRE_DATA_DIR      directory of CSVs written by `python -m data.generate`; unset = generate in memory
  TRUEACRE_SEED          RNG seed for in-memory generation (default: data.generate.DEFAULT_SEED)
  TRUEACRE_CORS_ORIGINS  comma-separated browser origins allowed to call the API (default: Vite dev server)

The ground-truth table is never exposed: it is the answer key for tests only.

Run: uvicorn api.main:app --reload
"""
import os
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from data.generate import DEFAULT_SEED, generate, load_csvs
from engine.reconcile import reconcile
from engine.score import score

DATA_DIR = os.environ.get("TRUEACRE_DATA_DIR")
SEED = int(os.environ.get("TRUEACRE_SEED", DEFAULT_SEED))
CORS_ORIGINS = os.environ.get("TRUEACRE_CORS_ORIGINS", "http://localhost:5173").split(",")

app = FastAPI(title="TrueAcre")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

TABLES = load_csvs(Path(DATA_DIR)) if DATA_DIR else generate(seed=SEED)
SCORES = (
    score(reconcile(TABLES))
    .merge(TABLES["growers"][["grower_id", "name"]], on="grower_id")
    .sort_values(["fair_play_score", "grower_id", "season"])
)

SCORE_COLUMNS = [
    "grower_id", "name", "county", "state", "season", "fair_play_score", "label",
    "gap_fraction", "unsupported_acre_fraction", "unsupported_bushel_fraction", "coverage",
    "licensed_acres", "declared_acres", "delivered_bushels", "yield_ceiling", "max_bushels",
    "acre_gap", "bushel_gap", "has_purchases", "has_acreage", "has_deliveries",
]


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame rows as JSON-safe dicts (NaN becomes null)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


@app.get("/scores")
def list_scores(season: int | None = None, county: str | None = None, label: str | None = None) -> list[dict]:
    df = SCORES
    if season is not None:
        df = df[df["season"] == season]
    if county is not None:
        df = df[df["county"] == county]
    if label is not None:
        df = df[df["label"] == label]
    return _records(df[SCORE_COLUMNS])


@app.get("/growers/{grower_id}/seasons/{season}")
def grower_evidence(grower_id: str, season: int) -> dict:
    match = SCORES[(SCORES["grower_id"] == grower_id) & (SCORES["season"] == season)]
    if match.empty:
        raise HTTPException(status_code=404, detail="no data for that grower and season")
    row = match.iloc[0]

    purchases = TABLES["seed_purchases"]
    purchases = purchases[(purchases["grower_id"] == grower_id) & (purchases["season"] == season)]
    purchases = purchases.merge(TABLES["dealers"][["dealer_id", "name"]].rename(columns={"name": "dealer"}), on="dealer_id")
    purchases = purchases.merge(TABLES["varieties"], on="variety_id")
    purchases["acres_supported"] = purchases["units"] * purchases["seeds_per_unit"] / purchases["target_seeds_per_acre"]

    acreage = TABLES["acreage_reports"]
    acreage = acreage[(acreage["grower_id"] == grower_id) & (acreage["season"] == season)]
    receipts = TABLES["elevator_receipts"]
    receipts = receipts[(receipts["grower_id"] == grower_id) & (receipts["season"] == season)]
    yields = TABLES["county_yields"]
    yields = yields[(yields["county"] == row["county"]) & (yields["season"] == season)]

    return {
        "score": _records(match[SCORE_COLUMNS])[0],
        "purchases": _records(purchases[[
            "purchase_id", "dealer", "variety_id", "name", "units", "seeds_per_unit",
            "target_seeds_per_acre", "acres_supported",
        ]].rename(columns={"name": "variety"})),
        "acreage_reports": _records(acreage[["report_id", "crop", "acres"]]),
        "elevator_receipts": _records(receipts[["receipt_id", "elevator_id", "crop", "bushels"]]),
        "county_yield": _records(yields[["county", "state", "mean_yield", "std_yield"]])[0] if not yields.empty else None,
    }
