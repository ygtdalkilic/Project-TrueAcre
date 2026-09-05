import pandas as pd
import pytest

from data.generate import generate, write_csvs


@pytest.fixture(scope="module")
def tables():
    return generate(n_growers=120, n_ghost=6, n_missing_dealer=6, seed=7)


def test_same_seed_gives_identical_tables():
    a = generate(n_growers=40, n_ghost=2, n_missing_dealer=2, seed=1)
    b = generate(n_growers=40, n_ghost=2, n_missing_dealer=2, seed=1)
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_row_counts(tables):
    truth = tables["ground_truth"]
    assert len(tables["growers"]) == 120
    assert len(truth) == 120 * 2
    assert len(tables["acreage_reports"]) == 120 * 2
    per_grower = truth.drop_duplicates("grower_id")["case_type"].value_counts().to_dict()
    assert per_grower == {"clean": 108, "ghost_seed": 6, "missing_dealer": 6}


def test_every_grower_season_has_acreage_and_deliveries(tables):
    keys = tables["ground_truth"][["grower_id", "season"]]
    for name in ("acreage_reports", "elevator_receipts"):
        present = tables[name][["grower_id", "season"]].drop_duplicates()
        assert len(keys.merge(present)) == len(keys)


def test_case_type_invariants(tables):
    truth = tables["ground_truth"]
    clean = truth[truth.case_type == "clean"]
    ghost = truth[truth.case_type == "ghost_seed"]
    missing = truth[truth.case_type == "missing_dealer"]
    assert (clean.licensed_acres >= clean.planted_acres).all()
    assert (clean.hidden_units == 0).all()
    assert (ghost.licensed_acres < ghost.planted_acres).all()
    assert (ghost.hidden_units == 0).all()
    assert (missing.licensed_acres >= missing.planted_acres).all()
    assert (missing.hidden_units > 0).all()


def test_hidden_purchases_never_appear(tables):
    purchases = tables["seed_purchases"].merge(tables["dealers"], on="dealer_id")
    assert purchases["participating"].all()

    visible = purchases.merge(tables["varieties"], on="variety_id")
    visible["acres"] = visible.units * visible.seeds_per_unit / visible.target_seeds_per_acre
    visible_acres = visible.groupby(["grower_id", "season"])["acres"].sum()
    truth = tables["ground_truth"].set_index(["grower_id", "season"])

    clean = truth[truth.case_type == "clean"]
    assert (visible_acres.reindex(clean.index) - clean.licensed_acres).abs().max() < 0.1
    missing = truth[truth.case_type == "missing_dealer"]
    assert (visible_acres.reindex(missing.index).fillna(0) < missing.licensed_acres).all()


def test_csv_round_trip(tmp_path, tables):
    write_csvs(tables, tmp_path)
    for name, df in tables.items():
        back = pd.read_csv(tmp_path / f"{name}.csv")
        assert len(back) == len(df)
        assert list(back.columns) == list(df.columns)
