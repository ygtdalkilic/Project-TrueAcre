"""Reconcile the three data sources per grower, season, and crop.

Pure function: takes the input tables and returns one row per grower-season-crop with the
quantities the score is built from. Nothing here decides anything; it only measures gaps.

Only crops the company licenses are scored: a crop counts if at least one variety in the
varieties table belongs to it. A grower's acreage or deliveries for any other crop are ignored.

Acreage reports and elevator receipts name the crop, not the brand. Acres the grower states were
planted with other seed (the optional seed_statements table) are subtracted before measuring a gap.
"""
import pandas as pd

from data.geography import neighbors, place

# Yield ceiling = county mean + YIELD_SIGMAS * std. Generous on purpose: an honest grower with an
# exceptional year must never be flagged. At 2 sigma, roughly 1 in 40 honest grower-seasons beat the
# ceiling; one of them exceeded the score tolerance in synthetic testing. 3 sigma leaves ~1 in 700.
YIELD_SIGMAS = 3.0
KEY = ["grower_id", "season", "crop"]


def area_dealers(dealers: pd.DataFrame, county: str, state: str) -> pd.DataFrame:
    """Dealers a grower in this county could plausibly buy from: those in the county and in every county
    bordering it (Census adjacency). A county not in the Census list falls back to every dealer in its
    state, so an unrecognized name can only lower coverage, never raise it."""
    home = place(county, state)
    keys = pd.Series([place(c, s) for c, s in zip(dealers["county"], dealers["state"])], index=dealers.index, dtype=object)
    if home in neighbors():
        area = neighbors()[home] | {home}
        return dealers[keys.map(lambda k: k in area)]
    return dealers[keys.map(lambda k: k[1] == home[1])]


def reconcile(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return one row per grower-season-crop with licensed acres, stated other-seed acres, declared
    acres, delivered bushels, the resulting gaps, source presence flags, and dealer coverage over the
    grower's county and the counties bordering it."""
    varieties = tables["varieties"]
    licensed_crops = set(varieties["crop"])

    purchases = tables["seed_purchases"].merge(varieties, on="variety_id")
    purchases["acres"] = purchases["units"] * purchases["seeds_per_unit"] / purchases["target_seeds_per_acre"]
    licensed = purchases.groupby(KEY)["acres"].sum().rename("licensed_acres").reset_index()

    acreage = tables["acreage_reports"]
    acreage = acreage[acreage["crop"].isin(licensed_crops)]
    declared = acreage.groupby(KEY)["acres"].sum().rename("declared_acres").reset_index()

    receipts = tables["elevator_receipts"]
    receipts = receipts[receipts["crop"].isin(licensed_crops)]
    delivered = receipts.groupby(KEY)["bushels"].sum().rename("delivered_bushels").reset_index()

    statements = tables.get("seed_statements", pd.DataFrame(columns=[*KEY, "other_seed_acres"]))
    stated = statements.groupby(KEY)["other_seed_acres"].sum().reset_index()

    out = pd.concat([licensed[KEY], declared[KEY], delivered[KEY]]).drop_duplicates()
    out = out.merge(tables["growers"][["grower_id", "county", "state"]], on="grower_id", how="left")
    for part in (licensed, declared, delivered, stated):
        out = out.merge(part, on=KEY, how="left")

    out["has_purchases"] = out["licensed_acres"].notna()
    out["has_acreage"] = out["declared_acres"].notna()
    out["has_deliveries"] = out["delivered_bushels"].notna()
    out["has_statement"] = out["other_seed_acres"].notna()
    amounts = ["licensed_acres", "declared_acres", "delivered_bushels", "other_seed_acres"]
    out[amounts] = out[amounts].fillna(0.0)

    # County names repeat across states (Boone, IA and Boone, IL), so every county join includes the state.
    yields = tables["county_yields"][["county", "state", "season", "crop", "mean_yield", "std_yield"]]
    out = out.merge(yields, on=["county", "state", "season", "crop"], how="left")
    out["yield_ceiling"] = out["mean_yield"] + YIELD_SIGMAS * out["std_yield"]
    explained_acres = out["licensed_acres"] + out["other_seed_acres"]
    out["max_bushels"] = explained_acres * out["yield_ceiling"]
    out["acre_gap"] = out["declared_acres"] - explained_acres
    out["bushel_gap"] = out["delivered_bushels"] - out["max_bushels"]

    places = out[["county", "state"]].dropna().drop_duplicates()
    coverage = pd.DataFrame(
        [(c, s, area_dealers(tables["dealers"], c, s)["participating"].mean()) for c, s in places.itertuples(index=False)],
        columns=["county", "state", "dealer_coverage"],
    )
    out = out.merge(coverage, on=["county", "state"], how="left")

    return out.sort_values(KEY).reset_index(drop=True)
