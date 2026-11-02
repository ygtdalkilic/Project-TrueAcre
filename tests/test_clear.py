import pandas as pd
import pytest

from data.generate import generate
from engine.clear import acres_to_clear, what_would_clear
from engine.reconcile import reconcile
from engine.replant import replant_signature
from engine.resolve import resolve
from engine.score import CONSISTENT, COVERAGE_MIN, INSUFFICIENT, REVIEW, score


def _with_extra_acres(rows: pd.DataFrame, extra) -> pd.DataFrame:
    """Re-score as if the grower had `extra` more licensed acres."""
    r = rows.copy()
    r["licensed_acres"] = r["licensed_acres"] + extra
    explained = r["licensed_acres"] + r["other_seed_acres"]
    r["acre_gap"] = r["declared_acres"] - explained
    r["max_bushels"] = explained * r["yield_ceiling"]
    r["bushel_gap"] = r["delivered_bushels"] - r["max_bushels"]
    return score(r)


@pytest.fixture(scope="module")
def scored():
    raw = generate(seed=11, messy_names=False)
    out = replant_signature(score(reconcile(resolve(raw))))
    return out.merge(raw["ground_truth"][["grower_id", "season", "case_type"]], on=["grower_id", "season"])


def test_acres_to_clear_is_the_exact_threshold(scored):
    flagged = scored[scored["label"] != CONSISTENT]
    assert len(flagged) > 0
    needed = flagged.apply(acres_to_clear, axis=1)
    assert (needed > 0).all()
    assert (_with_extra_acres(flagged, needed + 1e-6)["label"] == CONSISTENT).all()
    big = needed > 1
    assert (_with_extra_acres(flagged[big], needed[big] - 1)["label"] != CONSISTENT).all()
    assert (scored.loc[scored["label"] == CONSISTENT].apply(acres_to_clear, axis=1) == 0).all()


def test_what_would_clear_names_the_missing_record():
    row = pd.Series(dict(acre_gap=50.0, declared_acres=150.0, bushel_gap=-100.0, delivered_bushels=5000.0,
                         yield_ceiling=65.0, has_purchases=True, has_statement=False, coverage=0.5,
                         county="Story", state="IA"))
    purchases = pd.DataFrame({"variety": ["TA 2410", "TA 2620"], "acres_supported": [60.0, 40.0],
                              "target_seeds_per_acre": [140_000, 70_000], "seeds_per_unit": [140_000, 140_000]})
    dealers = pd.DataFrame({"dealer_id": ["D1", "D2", "D3"], "name": ["Ames Seed", "Boone Co-op", "Far Away"],
                            "county": ["Story", "Boone", "Wright"], "state": ["IA"] * 3,
                            "participating": [True, False, False]})
    out = what_would_clear(row, purchases, dealers)
    assert out["acres"] == pytest.approx(50 - 0.05 * 150)
    assert out["units"] == {"variety": "TA 2410", "units": 43}  # 1 acre per unit of the main variety
    assert out["needs"] == ["statement"]
    assert out["non_reporting_dealers"] == ["Boone Co-op"]  # next door; Wright does not border Story


def test_replant_signal_marks_only_saved_seed(scored):
    assessable = scored[scored["has_statement"] & (scored["coverage"] >= COVERAGE_MIN) & scored["has_purchases"]]
    ghost = assessable[assessable["case_type"] == "ghost_seed"]
    assert len(ghost) > 0 and ghost["replant_signal"].all()
    assert not scored.loc[scored["case_type"] != "ghost_seed", "replant_signal"].any()
    assert (ghost["replant_from_season"] < ghost["season"]).all()


def test_replant_signal_never_changes_score_or_label(scored):
    plain = score(reconcile(resolve(generate(seed=11, messy_names=False))))
    merged = plain.merge(scored, on=["grower_id", "season", "crop"], suffixes=("", "_r"))
    assert (merged["fair_play_score"] == merged["fair_play_score_r"]).all()
    assert (merged["label"] == merged["label_r"]).all()
    assert set(scored["label"]) <= {CONSISTENT, INSUFFICIENT, REVIEW}
