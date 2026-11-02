import pandas as pd
import pytest

from data.generate import REPORTING_JITTER, generate
from data.schemas import SeedPurchase, columns
from data.geography import neighbors, normalize_county, place
from engine.reconcile import area_dealers, reconcile
from engine.score import ACRE_TOLERANCE
from engine.resolve import resolve


@pytest.fixture
def tiny():
    """Three growers in county X, season 2024, numbers chosen so expected results are hand-calculable.

    V1: 140k seeds/unit at 140k seeds/acre -> 1 acre per unit.
    V2: 140k seeds/unit at 70k seeds/acre  -> 2 acres per unit.
    County yield mean 50, std 5 -> ceiling 50 + 3 * 5 = 65 bu/acre.
    Dealers: 2 in county, 1 participating -> coverage 0.5.
    """
    return {
        "growers": pd.DataFrame({
            "grower_id": ["G1", "G2", "G3"], "name": ["a", "b", "c"],
            "county": ["X", "X", "X"], "state": ["IA", "IA", "IA"],
        }),
        "dealers": pd.DataFrame({
            "dealer_id": ["D1", "D2"], "name": ["d1", "d2"], "county": ["X", "X"],
            "state": ["IA", "IA"], "participating": [True, False],
        }),
        "varieties": pd.DataFrame({
            "variety_id": ["V1", "V2"], "name": ["v1", "v2"], "crop": ["soybeans", "soybeans"],
            "seeds_per_unit": [140_000, 140_000], "target_seeds_per_acre": [140_000, 70_000],
        }),
        "seed_purchases": pd.DataFrame([
            ("P1", "G1", "D1", "V1", 2024, 60),
            ("P2", "G1", "D1", "V1", 2024, 40),
            ("P3", "G2", "D1", "V2", 2024, 10),
        ], columns=columns(SeedPurchase)),
        # external records as they look after engine.resolve has attached grower_id
        "acreage_reports": pd.DataFrame({
            "report_id": ["A1", "A2"], "grower_id": ["G1", "G1"], "season": [2024, 2024],
            "crop": ["soybeans", "corn"], "acres": [150.0, 1000.0],
        }),
        "elevator_receipts": pd.DataFrame({
            "receipt_id": ["R1", "R2", "R3", "R4"], "grower_id": ["G1", "G1", "G1", "G3"],
            "elevator_id": ["E1", "E2", "E1", "E1"], "season": [2024] * 4,
            "crop": ["soybeans", "soybeans", "corn", "soybeans"], "bushels": [5000.0, 2500.0, 50000.0, 3000.0],
        }),
        "county_yields": pd.DataFrame({
            "county": ["X"], "state": ["IA"], "season": [2024], "crop": ["soybeans"],
            "mean_yield": [50.0], "std_yield": [5.0],
        }),
    }


def test_full_grower_hand_calculated(tiny):
    row = reconcile(tiny).set_index("grower_id").loc["G1"]
    assert row.licensed_acres == 100.0
    assert row.declared_acres == 150.0
    assert row.delivered_bushels == 7500.0
    assert row.yield_ceiling == 65.0
    assert row.max_bushels == 6500.0
    assert row.acre_gap == 50.0
    assert row.bushel_gap == 1000.0
    assert row.dealer_coverage == 0.5
    assert row.has_purchases and row.has_acreage and row.has_deliveries


def test_other_crops_are_ignored(tiny):
    with_corn = reconcile(tiny).set_index("grower_id").loc["G1"]
    tiny["acreage_reports"] = tiny["acreage_reports"].query("crop == 'soybeans'")
    tiny["elevator_receipts"] = tiny["elevator_receipts"].query("crop == 'soybeans'")
    without_corn = reconcile(tiny).set_index("grower_id").loc["G1"]
    pd.testing.assert_series_equal(with_corn, without_corn)


def test_purchases_only(tiny):
    row = reconcile(tiny).set_index("grower_id").loc["G2"]
    assert row.licensed_acres == 20.0
    assert row.has_purchases and not row.has_acreage and not row.has_deliveries
    assert row.declared_acres == 0.0 and row.delivered_bushels == 0.0
    assert row.acre_gap == -20.0
    assert row.bushel_gap == -1300.0


def test_deliveries_only(tiny):
    row = reconcile(tiny).set_index("grower_id").loc["G3"]
    assert not row.has_purchases and not row.has_acreage and row.has_deliveries
    assert row.licensed_acres == 0.0 and row.max_bushels == 0.0
    assert row.acre_gap == 0.0
    assert row.bushel_gap == 3000.0


def test_one_row_per_grower_season(tiny):
    out = reconcile(tiny)
    assert list(out["grower_id"]) == ["G1", "G2", "G3"]
    assert list(out["crop"]) == ["soybeans"] * 3
    assert not out.duplicated(["grower_id", "season", "crop"]).any()


def test_each_licensed_crop_is_scored_separately(tiny):
    """G1 also licenses wheat: 10 units of V3 at 1 acre per unit, declares 12 wheat acres."""
    tiny["varieties"] = pd.concat([tiny["varieties"], pd.DataFrame({
        "variety_id": ["V3"], "name": ["w1"], "crop": ["wheat"],
        "seeds_per_unit": [1_000_000], "target_seeds_per_acre": [1_000_000],
    })], ignore_index=True)
    tiny["seed_purchases"] = pd.concat([tiny["seed_purchases"], pd.DataFrame(
        [("P4", "G1", "D1", "V3", 2024, 10)], columns=columns(SeedPurchase))], ignore_index=True)
    tiny["acreage_reports"] = pd.concat([tiny["acreage_reports"], pd.DataFrame({
        "report_id": ["A3"], "grower_id": ["G1"], "season": [2024], "crop": ["wheat"], "acres": [12.0],
    })], ignore_index=True)
    tiny["county_yields"] = pd.concat([tiny["county_yields"], pd.DataFrame({
        "county": ["X"], "state": ["IA"], "season": [2024], "crop": ["wheat"], "mean_yield": [40.0], "std_yield": [4.0],
    })], ignore_index=True)

    out = reconcile(tiny).set_index(["grower_id", "crop"])
    soy, wheat = out.loc[("G1", "soybeans")], out.loc[("G1", "wheat")]
    assert soy.licensed_acres == 100.0 and soy.declared_acres == 150.0  # unchanged by the wheat rows
    assert wheat.licensed_acres == 10.0 and wheat.declared_acres == 12.0 and wheat.acre_gap == 2.0
    assert wheat.yield_ceiling == 40.0 + 3 * 4.0 and wheat.delivered_bushels == 0.0
    assert "corn" not in out.index.get_level_values("crop")  # still not a licensed crop


def test_seed_statement_explains_other_seed_acres(tiny):
    """G1 states 30 acres of another company's seed: gap 150 - 100 - 30 = 20, ceiling covers 130 acres."""
    assert not reconcile(tiny)["has_statement"].any()  # table absent: nobody has a statement
    tiny["seed_statements"] = pd.DataFrame({
        "grower_id": ["G1"], "season": [2024], "crop": ["soybeans"], "other_seed_acres": [30.0],
    })
    out = reconcile(tiny).set_index("grower_id")
    g1 = out.loc["G1"]
    assert g1.has_statement and g1.other_seed_acres == 30.0
    assert g1.acre_gap == 20.0
    assert g1.max_bushels == 130 * 65.0 and g1.bushel_gap == 7500.0 - 130 * 65.0
    assert not out.loc["G2", "has_statement"] and out.loc["G2", "other_seed_acres"] == 0.0


def test_same_county_name_in_another_state_stays_separate(tiny):
    """G4 farms in a county also named X, but in NE, with its own yield and a non-reporting dealer."""
    tiny["growers"] = pd.concat([tiny["growers"], pd.DataFrame({
        "grower_id": ["G4"], "name": ["d"], "county": ["X"], "state": ["NE"],
    })], ignore_index=True)
    tiny["dealers"] = pd.concat([tiny["dealers"], pd.DataFrame({
        "dealer_id": ["D3"], "name": ["d3"], "county": ["X"], "state": ["NE"], "participating": [False],
    })], ignore_index=True)
    tiny["seed_purchases"] = pd.concat([tiny["seed_purchases"], pd.DataFrame(
        [("P4", "G4", "D3", "V1", 2024, 10)], columns=columns(SeedPurchase))], ignore_index=True)
    tiny["county_yields"] = pd.concat([tiny["county_yields"], pd.DataFrame({
        "county": ["X"], "state": ["NE"], "season": [2024], "crop": ["soybeans"], "mean_yield": [30.0], "std_yield": [2.0],
    })], ignore_index=True)

    out = reconcile(tiny)
    assert not out.duplicated(["grower_id", "season", "crop"]).any()
    rows = out.set_index("grower_id")
    assert rows.loc["G1", "yield_ceiling"] == 65.0 and rows.loc["G1", "dealer_coverage"] == 0.5
    assert rows.loc["G4", "yield_ceiling"] == 36.0 and rows.loc["G4", "dealer_coverage"] == 0.0


@pytest.mark.parametrize("raw, expected", [
    ("Story", "story"), ("Story County", "story"), ("STORY COUNTY", "story"),
    ("St. Louis County", "stlouis"), ("Saint Louis", "stlouis"), ("St. Louis city", "stlouiscity"),
    ("De Witt", "dewitt"), ("DeWitt County", "dewitt"), ("Doña Ana", "donaana"), ("Prince George's", "princegeorges"),
])
def test_normalize_county(raw, expected):
    assert normalize_county(raw) == expected


def test_census_adjacency_loads_and_names_are_distinct():
    adjacency = neighbors()
    assert len(adjacency) > 3000  # every US county and equivalent
    assert place("Boone", "IA") in adjacency[place("Story County", "IA")]
    assert place("Boone", "IL") not in adjacency[place("Story County", "IA")]  # same name, other state
    assert place("Richmond city", "VA") != place("Richmond County", "VA")


def test_against_synthetic_ground_truth():
    tables = resolve(generate(n_growers=150, n_ghost=8, n_missing_dealer=8, seed=3, messy_names=False))
    truth = tables["ground_truth"].rename(columns={"licensed_acres": "true_licensed_acres"})
    out = reconcile(tables).merge(truth, on=["grower_id", "season"])
    assert len(out) == 150 * 2

    clean = out[out.case_type == "clean"]
    assert (clean.licensed_acres - clean.true_licensed_acres).abs().max() < 0.1  # truth is rounded to 0.1 acre
    # honest growers: declared acres exceed licensed ones by at most the reporting jitter, plus 0.05 acre
    # because declared acres are rounded to one decimal
    jitter = 1 - 1 / REPORTING_JITTER[1]
    assert (clean.acre_gap <= jitter * clean.declared_acres + 0.05).all()

    # ghost seed: the acre gap always exceeds what the score treats as noise, so it can be flagged
    ghost = out[out.case_type == "ghost_seed"]
    assert (ghost.acre_gap > ACRE_TOLERANCE * ghost.declared_acres).all()
    assert (ghost.dealer_coverage == 1.0).all()

    # split brand: with a statement, the other company's acres close the gap; without one, it stays open
    split = out[out.case_type == "split_brand"]
    assert (split.dealer_coverage == 1.0).all()
    stated, unstated = split[split.has_statement], split[~split.has_statement]
    assert (stated.acre_gap <= jitter * stated.declared_acres + 0.05).all()
    assert (unstated.acre_gap > ACRE_TOLERANCE * unstated.declared_acres).all()

    # missing dealer: the engine sees fewer licensed acres than were really bought
    missing = out[out.case_type == "missing_dealer"]
    assert (missing.licensed_acres < missing.true_licensed_acres).all()
    assert (missing.dealer_coverage < 1.0).all()

    # neighbor dealer: every dealer at home reports, but one next door does not, and coverage shows it
    neighbor = out[out.case_type == "neighbor_dealer"]
    assert (neighbor.licensed_acres < neighbor.true_licensed_acres).all()
    assert (neighbor.dealer_coverage < 1.0).all()


def test_coverage_includes_bordering_counties():
    """Story, IA borders Boone, IA. A non-reporting dealer in Boone lowers Story's coverage; one in
    Wright, IA (not a neighbor) does not. An unknown county falls back to every dealer in its state."""
    dealers = pd.DataFrame({
        "dealer_id": ["D1", "D2", "D3", "D4"], "name": ["a", "b", "c", "d"],
        "county": ["Story", "Story County", "BOONE", "Wright"], "state": ["IA", "IA", "ia", "IA"],
        "participating": [True, True, False, False],
    })
    assert set(area_dealers(dealers, "Story", "IA")["dealer_id"]) == {"D1", "D2", "D3"}
    assert set(area_dealers(dealers, "Nowhere", "IA")["dealer_id"]) == {"D1", "D2", "D3", "D4"}
    assert area_dealers(dealers, "Story", "NE").empty
