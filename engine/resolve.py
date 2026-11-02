"""Entity resolution: attach the seed company's grower_id to external records.

Seed purchases already carry grower_id because they are the company's own customer records.
Acreage reports and elevator receipts only carry a name, a county, and (acreage only) a farm number.

Rules, tried in order, each accepted only when exactly ONE registered grower qualifies:
  1. farm number equals a registered farm number in the same county and state (FSA numbers farms
     per county office, so the same number recurs in other counties)
  2. normalized name, county, and state equal a registered grower
  3. normalized name is similar (ratio >= FUZZY_MIN) to a grower in the same county and state
Anything else stays unmatched and is excluded. A wrong match is worse than a missed one.
"""
import difflib
import re

import pandas as pd

FUZZY_MIN = 0.85  # difflib ratio; one dropped letter in a 9-letter name scores ~0.94, different names score far lower
NOISE_WORDS = {"farm", "farms"}  # business suffixes that do not identify a person

SOURCES = (  # table, name column, farm-number column (or None), record id column
    ("acreage_reports", "operator_name", "farm_number", "report_id"),
    ("elevator_receipts", "seller_name", None, "receipt_id"),
)


def normalize_name(name: str) -> str:
    """lowercase; 'last, first' -> 'first last'; drop punctuation, single-letter initials, and noise words."""
    name = name.lower()
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first} {last}"
    tokens = re.sub(r"[^a-z ]", " ", name).split()
    return " ".join(t for t in tokens if len(t) > 1 and t not in NOISE_WORDS)


def _unique(candidates, method):
    ids = set(candidates)
    return (ids.pop(), method) if len(ids) == 1 else (None, f"ambiguous {method}")


def _resolve(records: pd.DataFrame, name_col: str, farm_col: str | None, growers: pd.DataFrame):
    """Return (grower_id, match_method) lists aligned with the rows of `records`."""
    reg = growers.assign(norm=growers["name"].map(normalize_name))
    by_farm = reg.dropna(subset=["farm_number"]).groupby(["farm_number", "county", "state"])["grower_id"].agg(list)
    by_key = reg.groupby(["norm", "county", "state"])["grower_id"].agg(list)
    by_county = {place: group for place, group in reg.groupby(["county", "state"])}  # county names repeat across states

    ids, methods = [], []
    for _, rec in records.iterrows():
        gid, method = None, "no match"
        place = (rec["county"], rec["state"])
        farm = rec[farm_col] if farm_col else None
        if isinstance(farm, str) and (farm, *place) in by_farm.index:
            gid, method = _unique(by_farm[(farm, *place)], "farm number")
        if gid is None:
            norm = normalize_name(rec[name_col])
            if (norm, *place) in by_key.index:
                gid, method = _unique(by_key[(norm, *place)], "exact name")
            elif place in by_county:
                local = by_county[place]
                close = [
                    g for g, n in zip(local["grower_id"], local["norm"])
                    if difflib.SequenceMatcher(None, norm, n).ratio() >= FUZZY_MIN
                ]
                if close:
                    gid, method = _unique(close, "fuzzy name")
        ids.append(gid)
        methods.append(method)
    return ids, methods


def resolve(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Return a copy of `tables` where acreage_reports and elevator_receipts carry grower_id and
    match_method, unmatched records are removed, and an `unmatched` table lists them with the reason."""
    out = dict(tables)
    unmatched = []
    for table, name_col, farm_col, id_col in SOURCES:
        df = tables[table].copy()
        df["grower_id"], df["match_method"] = _resolve(df, name_col, farm_col, tables["growers"])
        miss = df[df["grower_id"].isna()]
        unmatched.append(pd.DataFrame({
            "source": table, "record_id": miss[id_col], "name": miss[name_col],
            "county": miss["county"], "state": miss["state"], "reason": miss["match_method"],
        }))
        out[table] = df[df["grower_id"].notna()].reset_index(drop=True)
    out["unmatched"] = pd.concat(unmatched, ignore_index=True)
    return out
