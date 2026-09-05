import pandas as pd
import pytest

from data.generate import generate
from data.schemas import AcreageReport, ElevatorReceipt, SeedPurchase, columns
from engine.reconcile import reconcile


@pytest.fixture
def tiny():
    """Three growers in county X, season 2024, numbers chosen so expected results are hand-calculable.

    V1: 140k seeds/unit at 140k seeds/acre -> 1 acre per unit.
    V2: 140k seeds/unit at 70k seeds/acre  -> 2 acres per unit.
    County yield mean 50, std 5 -> ceiling 60 bu/acre.
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
        "acreage_reports": pd.DataFrame([
            ("A1", "G1", 2024, "soybeans", 150.0),
            ("A2", "G1", 2024, "corn", 1000.0),
        ], columns=columns(AcreageReport)),
        "elevator_receipts": pd.DataFrame([
            ("R1", "G1", "E1", 2024, "soybeans", 5000.0),
            ("R2", "G1", "E2", 2024, "soybeans", 2500.0),
            ("R3", "G1", "E1", 2024, "corn", 50000.0),
            ("R4", "G3", "E1", 2024, "soybeans", 3000.0),
        ], columns=columns(ElevatorReceipt)),
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
    assert row.yield_ceiling == 60.0
    assert row.max_bushels == 6000.0
    assert row.acre_gap == 50.0
    assert row.bushel_gap == 1500.0
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
    assert row.bushel_gap == -1200.0


def test_deliveries_only(tiny):
    row = reconcile(tiny).set_index("grower_id").loc["G3"]
    assert not row.has_purchases and not row.has_acreage and row.has_deliveries
    assert row.licensed_acres == 0.0 and row.max_bushels == 0.0
    assert row.acre_gap == 0.0
    assert row.bushel_gap == 3000.0


def test_one_row_per_grower_season(tiny):
    out = reconcile(tiny)
    assert list(out["grower_id"]) == ["G1", "G2", "G3"]
    assert not out.duplicated(["grower_id", "season"]).any()


def test_against_synthetic_ground_truth():
    tables = generate(n_growers=150, n_ghost=8, n_missing_dealer=8, seed=3)
    truth = tables["ground_truth"].rename(columns={"licensed_acres": "true_licensed_acres"})
    out = reconcile(tables).merge(truth, on=["grower_id", "season"])
    assert len(out) == 150 * 2

    clean = out[out.case_type == "clean"]
    assert (clean.licensed_acres - clean.true_licensed_acres).abs().max() < 0.1
    # honest growers: declared acres never exceed licensed by more than the 1% reporting jitter
    assert (clean.acre_gap <= 0.011 * clean.declared_acres).all()

    # ghost seed: bought for at most ~63% of planted acres, so the acre gap is always large
    ghost = out[out.case_type == "ghost_seed"]
    assert (ghost.acre_gap > 0.3 * ghost.declared_acres).all()
    assert (ghost.dealer_coverage == 1.0).all()

    # missing dealer: the engine sees fewer licensed acres than were really bought
    missing = out[out.case_type == "missing_dealer"]
    assert (missing.licensed_acres < missing.true_licensed_acres).all()
    assert (missing.dealer_coverage < 1.0).all()
