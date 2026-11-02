"""Turn reconciliation rows into a Fair-Play Score and a label.

Score: how much of what the grower declared or delivered is NOT backed by licensed seed.
Label: whether the data is complete enough to say anything about that gap.
A large gap with thin data is "insufficient data", never "review recommended". Thin data means
low dealer coverage, or no seed statement: without the grower's own count of acres planted with
other seed, another company's seed and saved seed look exactly the same.
"""
import numpy as np
import pandas as pd

# Acres are the strong signal: both the seed and the acreage are recorded by third parties, and the
# only slack is reporting jitter. Bushels are weak: yield varies by farm, grain is shared with
# landlords, custom-harvested, or sold on behalf of others. So a bushel gap must be large to count.
ACRE_TOLERANCE = 0.05  # unsupported share of declared acres at or below this is consistent
BUSHEL_TOLERANCE = 0.25  # unsupported share of delivered bushels at or below this is consistent
COVERAGE_MIN = 0.90  # dealer coverage needed before a gap becomes "review recommended"

CONSISTENT = "consistent"
INSUFFICIENT = "insufficient data"
REVIEW = "review recommended"


def _unsupported(gap: pd.Series, total: pd.Series) -> pd.Series:
    """Share of `total` not backed by licensed seed, in [0, 1]. Zero when there is no gap, no total, or no data."""
    frac = gap.clip(lower=0) / total.where(total > 0)
    return frac.fillna(0.0).clip(upper=1.0)


def score(recon: pd.DataFrame) -> pd.DataFrame:
    """Add unsupported fractions, fair_play_score (0-100, 100 = fully consistent), coverage, and label."""
    out = recon.copy()
    out["unsupported_acre_fraction"] = _unsupported(out["acre_gap"], out["declared_acres"])
    out["unsupported_bushel_fraction"] = _unsupported(out["bushel_gap"], out["delivered_bushels"])
    out["gap_fraction"] = out[["unsupported_acre_fraction", "unsupported_bushel_fraction"]].max(axis=1)
    out["fair_play_score"] = (100 * (1 - out["gap_fraction"])).round().astype(int)

    # A gap can only be judged if we see the grower's purchases and at least one thing to compare them to.
    judgeable = out["has_purchases"] & (out["has_acreage"] | out["has_deliveries"])
    out["coverage"] = out["dealer_coverage"].fillna(0.0).where(judgeable, 0.0)

    has_gap = (out["unsupported_acre_fraction"] > ACRE_TOLERANCE) | (
        out["unsupported_bushel_fraction"] > BUSHEL_TOLERANCE
    )
    out["label"] = np.select(
        [~has_gap, (out["coverage"] >= COVERAGE_MIN) & out["has_statement"]], [CONSISTENT, REVIEW], default=INSUFFICIENT
    )
    return out
