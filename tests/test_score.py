import numpy as np
import pandas as pd
import pytest

from data.generate import generate
from engine.reconcile import reconcile
from engine.resolve import resolve
from engine.score import CONSISTENT, INSUFFICIENT, REVIEW, score


def _row(**overrides):
    """One reconciled grower-season. Defaults: 100 licensed acres, 150 declared, 7500 bu delivered
    against a 6000 bu ceiling, all sources present, full dealer coverage."""
    base = dict(
        grower_id="G", season=2024, licensed_acres=100.0, declared_acres=150.0, delivered_bushels=7500.0,
        max_bushels=6000.0, has_purchases=True, has_acreage=True, has_deliveries=True, dealer_coverage=1.0,
    )
    base.update(overrides)
    base["acre_gap"] = base["declared_acres"] - base["licensed_acres"]
    base["bushel_gap"] = base["delivered_bushels"] - base["max_bushels"]
    return score(pd.DataFrame([base])).iloc[0]


def test_large_gap_with_full_coverage_is_review():
    r = _row()
    assert r.unsupported_acre_fraction == pytest.approx(1 / 3)
    assert r.unsupported_bushel_fraction == pytest.approx(0.2)
    assert r.fair_play_score == 67
    assert r.label == REVIEW


def test_large_gap_with_partial_coverage_is_insufficient():
    r = _row(dealer_coverage=2 / 3)
    assert r.fair_play_score == 67
    assert r.label == INSUFFICIENT


def test_small_gap_is_consistent():
    r = _row(declared_acres=101.0, delivered_bushels=5000.0)
    assert r.fair_play_score == 99
    assert r.label == CONSISTENT


def test_no_purchases_is_insufficient_not_review():
    r = _row(licensed_acres=0.0, max_bushels=0.0, has_purchases=False,
             declared_acres=200.0, delivered_bushels=10000.0)
    assert r.fair_play_score == 0
    assert r.coverage == 0.0
    assert r.label == INSUFFICIENT


def test_purchases_only_is_consistent():
    r = _row(declared_acres=0.0, delivered_bushels=0.0, has_acreage=False, has_deliveries=False)
    assert r.fair_play_score == 100
    assert r.label == CONSISTENT


def test_bushel_only_gap_needs_to_be_large():
    # 100 licensed acres cover the 100 declared; only the bushels are over the 6000 bu ceiling
    modest = _row(declared_acres=100.0, delivered_bushels=6600.0)  # 9% unsupported: an exceptional year
    assert modest.unsupported_bushel_fraction == pytest.approx(600 / 6600)
    assert modest.label == CONSISTENT
    large = _row(declared_acres=100.0, delivered_bushels=9000.0)  # 33% unsupported: beyond yield variance
    assert large.label == REVIEW


def test_missing_yield_reference_ignores_bushels():
    r = _row(declared_acres=100.0, max_bushels=np.nan)
    assert r.unsupported_bushel_fraction == 0.0
    assert r.label == CONSISTENT


@pytest.mark.parametrize("seed", [42, 7, 2025])
def test_labels_match_synthetic_ground_truth(seed):
    tables = resolve(generate(seed=seed, messy_names=False))  # exact names: every record links, so labels are exact
    truth = tables["ground_truth"][["grower_id", "season", "case_type"]]
    out = score(reconcile(tables)).merge(truth, on=["grower_id", "season"])
    assert len(out) == len(truth)

    expected = {"clean": CONSISTENT, "ghost_seed": REVIEW, "missing_dealer": INSUFFICIENT}
    mismatches = out[out["label"] != out["case_type"].map(expected)]
    assert mismatches.empty, mismatches[["grower_id", "season", "case_type", "label", "gap_fraction", "coverage"]]
