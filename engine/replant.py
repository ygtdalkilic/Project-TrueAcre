"""Replant signature: the usual pattern of saved seed across seasons, shown as context next to the score.

Saved seed rarely starts from nothing. A grower buys licensed seed for their acreage one season, then
buys for less of a similar acreage the next. When licensed purchases (plus stated other seed)
explained the declared acres in an earlier season and explain far less of a similar acreage now,
the row carries the signature.

It is assessed only where the row could support a review at all (purchases, acreage, a seed
statement, enough dealer coverage), and it never changes the score or the label.
"""
import pandas as pd

from engine.score import COVERAGE_MIN

REPLANT_SHARE_DROP = 0.30  # explained share of declared acres must fall at least this much from an earlier season
REPLANT_ACRE_BAND = 0.20  # while declared acres stay within this fraction of that season's


def replant_signature(scored: pd.DataFrame) -> pd.DataFrame:
    """Add explained_share, replant_signal (bool), and replant_from_season (the earlier season, or NA)."""
    out = scored.copy()
    explained = out["licensed_acres"] + out["other_seed_acres"]
    out["explained_share"] = (explained / out["declared_acres"].where(out["declared_acres"] > 0)).clip(upper=1.0)
    assessable = out["has_purchases"] & out["has_acreage"] & out["has_statement"] & (out["coverage"] >= COVERAGE_MIN)

    signal = pd.Series(False, index=out.index)
    source = pd.Series(pd.NA, index=out.index, dtype="Int64")
    for _, group in out.groupby(["grower_id", "crop"]):
        for idx, row in group.iterrows():
            if not assessable[idx]:
                continue
            earlier = group[(group["season"] < row["season"]) & group["explained_share"].notna()]
            match = earlier[
                (earlier["explained_share"] - row["explained_share"] >= REPLANT_SHARE_DROP)
                & ((row["declared_acres"] / earlier["declared_acres"] - 1).abs() <= REPLANT_ACRE_BAND)
            ]
            if not match.empty:
                signal[idx] = True
                source[idx] = int(match["season"].max())
    out["replant_signal"] = signal
    out["replant_from_season"] = source
    return out
