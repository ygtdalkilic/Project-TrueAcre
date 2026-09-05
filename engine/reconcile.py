"""Reconcile the three data sources per grower per season.

Pure function: takes the input tables and returns one row per grower-season with the
quantities the score is built from. Nothing here decides anything; it only measures gaps.
"""
import pandas as pd

# Yield ceiling = county mean + YIELD_SIGMAS * std. Generous on purpose: an honest grower with an
# exceptional year must never be flagged. At 2 sigma, roughly 1 in 40 honest grower-seasons beat the
# ceiling; one of them exceeded the score tolerance in synthetic testing. 3 sigma leaves ~1 in 700.
YIELD_SIGMAS = 3.0
KEY = ["grower_id", "season"]


def reconcile(tables: dict[str, pd.DataFrame], crop: str = "soybeans") -> pd.DataFrame:
    """Return one row per grower-season with licensed acres, declared acres, delivered bushels,
    the resulting gaps, source presence flags, and county dealer coverage."""
    purchases = tables["seed_purchases"].merge(tables["varieties"], on="variety_id")
    purchases = purchases[purchases["crop"] == crop]
    purchases["acres"] = purchases["units"] * purchases["seeds_per_unit"] / purchases["target_seeds_per_acre"]
    licensed = purchases.groupby(KEY)["acres"].sum().rename("licensed_acres").reset_index()

    acreage = tables["acreage_reports"]
    declared = acreage[acreage["crop"] == crop].groupby(KEY)["acres"].sum().rename("declared_acres").reset_index()

    receipts = tables["elevator_receipts"]
    delivered = (
        receipts[receipts["crop"] == crop].groupby(KEY)["bushels"].sum().rename("delivered_bushels").reset_index()
    )

    out = pd.concat([licensed[KEY], declared[KEY], delivered[KEY]]).drop_duplicates()
    out = out.merge(tables["growers"][["grower_id", "county", "state"]], on="grower_id", how="left")
    for part in (licensed, declared, delivered):
        out = out.merge(part, on=KEY, how="left")

    out["has_purchases"] = out["licensed_acres"].notna()
    out["has_acreage"] = out["declared_acres"].notna()
    out["has_deliveries"] = out["delivered_bushels"].notna()
    amounts = ["licensed_acres", "declared_acres", "delivered_bushels"]
    out[amounts] = out[amounts].fillna(0.0)

    yields = tables["county_yields"]
    yields = yields[yields["crop"] == crop][["county", "season", "mean_yield", "std_yield"]]
    out = out.merge(yields, on=["county", "season"], how="left")
    out["yield_ceiling"] = out["mean_yield"] + YIELD_SIGMAS * out["std_yield"]
    out["max_bushels"] = out["licensed_acres"] * out["yield_ceiling"]
    out["acre_gap"] = out["declared_acres"] - out["licensed_acres"]
    out["bushel_gap"] = out["delivered_bushels"] - out["max_bushels"]

    coverage = tables["dealers"].groupby("county")["participating"].mean().rename("dealer_coverage").reset_index()
    out = out.merge(coverage, on="county", how="left")

    return out.sort_values(KEY).reset_index(drop=True)
