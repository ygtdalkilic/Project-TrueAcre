"""County yield reference from USDA NASS Quick Stats, so companies need not type it by hand.

For every county the company's growers farm in, every licensed crop, and every season in its
records, this pulls the county yield history and builds the county_yields table:
  mean_yield = that season's published county yield
  std_yield  = standard deviation of the same county's yields over the preceding HISTORY_YEARS
               seasons, as the measure of how much yields swing there

Requires a free API key from https://quickstats.nass.usda.gov/api (NASS_API_KEY). Yields are in
bushels per acre for grains and soybeans; cotton is published in pounds per acre, so a company
scoring cotton must also report deliveries in pounds.
"""
import os
import statistics

import httpx
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api import audit, models
from api.auth import current_membership
from api.datasets import _store
from api.db import get_db
from api.pipeline import load_tables
from api.security import RateLimiter

router = APIRouter(prefix="/api/data/county_yields", tags=["data"])

NASS_API_URL = os.environ.get("NASS_API_URL", "https://quickstats.nass.usda.gov/api/api_GET/")
NASS_API_KEY = os.environ.get("NASS_API_KEY")
HISTORY_YEARS = 10
MIN_HISTORY = 3  # fewer published years than this and no standard deviation is trustworthy
TIMEOUT = 60.0
COMMODITIES = {  # crop name as used in the varieties table -> Quick Stats filters
    "soybeans": {"commodity_desc": "SOYBEANS"},
    "corn": {"commodity_desc": "CORN", "util_practice_desc": "GRAIN"},
    "wheat": {"commodity_desc": "WHEAT"},
    "cotton": {"commodity_desc": "COTTON"},
}
IMPORT_LIMIT = RateLimiter(limit=5, window_seconds=600)  # per company; each import is many upstream calls
TRANSPORT: httpx.BaseTransport | None = None  # tests stand in a fake NASS here


def _series(client: httpx.Client, api_key: str, county: str, state: str, crop: str, first_year: int) -> dict[int, float]:
    params = {"key": api_key, "statisticcat_desc": "YIELD", "agg_level_desc": "COUNTY", "state_alpha": state,
              "county_name": county.upper(), "year__GE": first_year, "format": "JSON", **COMMODITIES[crop]}
    response = client.get(NASS_API_URL, params=params)
    response.raise_for_status()
    series = {}
    for row in response.json().get("data", []):
        try:
            series[int(row["year"])] = float(str(row["Value"]).replace(",", ""))
        except (KeyError, ValueError):
            continue  # suppressed values such as "(D)" carry no number
    return series


def fetch_county_yields(counties: list[tuple[str, str]], crops: list[str], seasons: list[int],
                        api_key: str, transport: httpx.BaseTransport | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Build the county_yields table. Returns (rows, notes about what could not be filled)."""
    unsupported = [c for c in crops if c not in COMMODITIES]
    crops = [c for c in crops if c in COMMODITIES]
    rows, notes = [], [f"no USDA mapping for crop '{c}'" for c in unsupported]
    first_year = min(seasons) - HISTORY_YEARS
    with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
        for county, state in counties:
            for crop in crops:
                series = _series(client, api_key, county, state, crop, first_year)
                for season in seasons:
                    history = [v for y, v in series.items() if season - HISTORY_YEARS <= y < season]
                    if season not in series or len(history) < MIN_HISTORY:
                        notes.append(f"{county}, {state} {crop} {season}: not enough published yields")
                        continue
                    rows.append({"county": county, "state": state, "season": season, "crop": crop,
                                 "mean_yield": series[season], "std_yield": round(statistics.stdev(history), 2)})
    return pd.DataFrame(rows, columns=["county", "state", "season", "crop", "mean_yield", "std_yield"]), notes


@router.post("/usda")
def import_from_usda(request: Request, membership: models.Membership = Depends(current_membership),
                     db: Session = Depends(get_db)) -> dict:
    if not NASS_API_KEY:
        raise HTTPException(status_code=503, detail="USDA import is not configured on this server (NASS_API_KEY)")
    IMPORT_LIMIT.check(str(membership.org_id))
    tables = load_tables(db, membership.organization)
    needed = [t for t in ("growers", "varieties", "seed_purchases", "acreage_reports", "elevator_receipts") if t not in tables]
    if needed:
        raise HTTPException(status_code=409, detail={"message": "upload these tables first", "missing": needed})

    counties = sorted(set(zip(tables["growers"]["county"], tables["growers"]["state"])))
    crops = sorted(set(tables["varieties"]["crop"]))
    seasons = sorted(set().union(*(set(tables[t]["season"].astype(int)) for t in
                                   ("seed_purchases", "acreage_reports", "elevator_receipts"))))
    try:
        df, notes = fetch_county_yields(counties, crops, seasons, NASS_API_KEY, TRANSPORT)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"USDA Quick Stats error: {e}")
    if df.empty:
        raise HTTPException(status_code=502, detail={"message": "USDA returned no usable yields", "notes": notes})

    ds = _store(db, membership.organization, "county_yields", df, membership.user_id)
    audit.record(db, "data.usda_import", request=request, user_id=membership.user_id, org_id=membership.org_id,
                 rows=ds.row_count, counties=len(counties), crops=crops, seasons=seasons)
    db.commit()
    return {"rows": ds.row_count, "notes": notes}
