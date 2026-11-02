"""What would clear a flag: the smallest record that would make a grower-season consistent, and the
records that would let a thin-data case be judged at all.

Pure and deterministic. It reads a scored row and never changes the score. It tells an analyst
exactly what to ask a grower for, which is usually one receipt, not an audit.
"""
import math

import pandas as pd

from engine.reconcile import area_dealers
from engine.score import ACRE_TOLERANCE, BUSHEL_TOLERANCE, COVERAGE_MIN


def acres_to_clear(row) -> float:
    """Additional licensed or stated other-seed acres that would bring both unsupported shares within
    tolerance. Each added acre lowers the acre gap by one and raises the bushel ceiling by yield_ceiling."""
    by_acres = row["acre_gap"] - ACRE_TOLERANCE * row["declared_acres"]
    ceiling = row["yield_ceiling"]
    by_bushels = (row["bushel_gap"] - BUSHEL_TOLERANCE * row["delivered_bushels"]) / ceiling if ceiling > 0 else 0.0
    return max(0.0, by_acres, by_bushels)


def what_would_clear(row, purchases: pd.DataFrame, dealers: pd.DataFrame) -> dict:
    """For one scored row:
      acres   extra licensed or stated other-seed acres that would make it consistent (0 if it is)
      units   the same in seed units of the variety the grower bought most of, or None
      needs   missing records that stop any conclusion: 'purchases' and/or 'statement'
      non_reporting_dealers  names of nearby dealers whose receipts would settle a low-coverage case
    `purchases` holds this grower-season-crop's purchases with variety, seeds_per_unit,
    target_seeds_per_acre, and acres_supported columns."""
    acres = acres_to_clear(row)
    units = None
    if acres > 0 and not purchases.empty:
        main = purchases.loc[purchases["acres_supported"].idxmax()]
        units = {"variety": main["variety"],
                 "units": math.ceil(acres * main["target_seeds_per_acre"] / main["seeds_per_unit"])}

    needs = []
    if acres > 0 and not row["has_purchases"]:
        needs.append("purchases")
    if acres > 0 and not row["has_statement"]:
        needs.append("statement")

    silent = []
    if acres > 0 and row["has_purchases"] and row["coverage"] < COVERAGE_MIN:
        nearby = area_dealers(dealers, row["county"], row["state"])
        silent = sorted(nearby.loc[~nearby["participating"].astype(bool), "name"])
    return {"acres": acres, "units": units, "needs": needs, "non_reporting_dealers": silent}
