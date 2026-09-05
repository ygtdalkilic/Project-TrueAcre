"""Synthetic data generator with seeded ghost-seed cases as ground truth.

Crop is soybeans only. Every grower is honest ("clean") unless designated:
  ghost_seed      buys seed for only part of the acreage and plants the rest with saved seed
  missing_dealer  honest, but part of the seed came from a dealer that does not report
                  into the system, so those receipts are invisible

Ghost-seed growers are placed in counties where every dealer participates, and
missing-dealer growers in counties with a non-participating dealer, so the engine
can be tested on both "review recommended" and "insufficient data" outcomes.

Run `python -m data.generate` to write CSVs to data/synthetic/.
"""
from __future__ import annotations

import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from data.schemas import (
    AcreageReport,
    CountyYield,
    Dealer,
    ElevatorReceipt,
    GroundTruth,
    Grower,
    SeedPurchase,
    Variety,
    columns,
)

CROP = "soybeans"
SEEDS_PER_UNIT = 140_000  # one soybean seed unit (bag) holds 140,000 seeds

# county, state, do all dealers report into the system, typical yield (bu/acre)
COUNTIES = [
    ("Story", "IA", True, 58.0),
    ("Boone", "IA", True, 56.0),
    ("McLean", "IL", True, 62.0),
    ("Champaign", "IL", True, 61.0),
    ("Wright", "IA", False, 54.0),
    ("Livingston", "IL", False, 59.0),
]
DEALERS_PER_COUNTY = 3  # in partial-coverage counties the last one does not report

VARIETIES = [  # name, target seeds per acre
    ("TA 2410", 130_000),
    ("TA 2620", 135_000),
    ("TA 2835", 140_000),
    ("TA 3105", 145_000),
    ("TA 3340", 150_000),
]

FIRST_NAMES = ["James", "Mary", "Robert", "Linda", "David", "Karen", "Daniel", "Susan",
               "Thomas", "Nancy", "Mark", "Lisa", "Paul", "Sandra", "Steven", "Donna"]
LAST_NAMES = ["Miller", "Schmidt", "Johnson", "Anderson", "Peterson", "Hansen", "Larson",
              "Olson", "Meyer", "Becker", "Wagner", "Fischer", "Weber", "Hoffman", "Koch", "Brandt"]


def _frame(rows, row_type) -> pd.DataFrame:
    return pd.DataFrame([asdict(r) for r in rows], columns=columns(row_type))


def generate(
    n_growers: int = 200,
    seasons: tuple[int, ...] = (2024, 2025),
    n_ghost: int = 10,
    n_missing_dealer: int = 10,
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)

    varieties = [
        Variety(f"V{i + 1:02d}", name, CROP, SEEDS_PER_UNIT, rate)
        for i, (name, rate) in enumerate(VARIETIES)
    ]

    dealers: list[Dealer] = []
    for county, state, full, _ in COUNTIES:
        for j in range(DEALERS_PER_COUNTY):
            participating = full or j < DEALERS_PER_COUNTY - 1
            dealers.append(
                Dealer(f"D{len(dealers) + 1:03d}", f"{county} Seed and Supply {j + 1}", county, state, participating)
            )

    county_yields = [
        CountyYield(county, state, season, CROP,
                    round(base + rng.normal(0, 2.0), 1), round(rng.uniform(5.0, 7.0), 1))
        for county, state, _, base in COUNTIES
        for season in seasons
    ]
    yield_lookup = {(y.county, y.season): y for y in county_yields}

    county_idx = rng.integers(0, len(COUNTIES), size=n_growers)
    growers = [
        Grower(
            f"G{i + 1:04d}",
            f"{FIRST_NAMES[rng.integers(len(FIRST_NAMES))]} {LAST_NAMES[rng.integers(len(LAST_NAMES))]}",
            COUNTIES[c][0],
            COUNTIES[c][1],
        )
        for i, c in enumerate(county_idx)
    ]

    full_cov = [i for i, c in enumerate(county_idx) if COUNTIES[c][2]]
    partial_cov = [i for i, c in enumerate(county_idx) if not COUNTIES[c][2]]
    if n_ghost > len(full_cov) or n_missing_dealer > len(partial_cov):
        raise ValueError("not enough growers in the right counties for the requested case counts")
    case_type = ["clean"] * n_growers
    for i in rng.choice(full_cov, size=n_ghost, replace=False):
        case_type[i] = "ghost_seed"
    for i in rng.choice(partial_cov, size=n_missing_dealer, replace=False):
        case_type[i] = "missing_dealer"

    purchases: list[SeedPurchase] = []
    reports: list[AcreageReport] = []
    receipts: list[ElevatorReceipt] = []
    truth: list[GroundTruth] = []

    for g, ctype in zip(growers, case_type):
        visible_dealers = [d for d in dealers if d.county == g.county and d.participating]
        for season in seasons:
            planted = float(rng.integers(20, 301) * 5)  # 100-1500 acres in steps of 5
            seed_acres = planted * (rng.uniform(0.2, 0.6) if ctype == "ghost_seed" else 1.0)
            hidden_frac = rng.uniform(0.4, 0.8) if ctype == "missing_dealer" else 0.0

            k = int(rng.integers(1, 4))  # 1-3 varieties
            chosen = [varieties[i] for i in rng.choice(len(varieties), size=k, replace=False)]
            licensed = 0.0
            hidden_units = 0
            for v in chosen:
                overbuy = rng.uniform(1.0, 1.05)
                units = math.ceil(seed_acres / k * v.target_seeds_per_acre / v.seeds_per_unit * overbuy)
                licensed += units * v.seeds_per_unit / v.target_seeds_per_acre
                hidden = int(round(units * hidden_frac))
                hidden_units += hidden
                if units - hidden > 0:
                    d = visible_dealers[rng.integers(len(visible_dealers))]
                    purchases.append(
                        SeedPurchase(f"P{len(purchases) + 1:05d}", g.grower_id, d.dealer_id,
                                     v.variety_id, season, units - hidden)
                    )

            reports.append(
                AcreageReport(f"A{len(reports) + 1:05d}", g.grower_id, season, CROP,
                              round(planted * rng.uniform(0.99, 1.01), 1))
            )

            cy = yield_lookup[(g.county, season)]
            realized_yield = max(15.0, rng.normal(cy.mean_yield, cy.std_yield))
            bushels = planted * realized_yield * rng.uniform(0.9, 1.0)  # some grain never reaches a visible elevator
            n_elevators = int(rng.integers(1, 3))
            for e, share in enumerate(rng.dirichlet(np.ones(n_elevators))):
                receipts.append(
                    ElevatorReceipt(f"R{len(receipts) + 1:05d}", g.grower_id, f"E-{g.county}-{e + 1}",
                                    season, CROP, float(round(bushels * share)))
                )

            truth.append(GroundTruth(g.grower_id, season, ctype, planted, round(licensed, 1), hidden_units))

    return {
        "growers": _frame(growers, Grower),
        "dealers": _frame(dealers, Dealer),
        "varieties": _frame(varieties, Variety),
        "seed_purchases": _frame(purchases, SeedPurchase),
        "acreage_reports": _frame(reports, AcreageReport),
        "elevator_receipts": _frame(receipts, ElevatorReceipt),
        "county_yields": _frame(county_yields, CountyYield),
        "ground_truth": _frame(truth, GroundTruth),
    }


def write_csvs(tables: dict[str, pd.DataFrame], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)


if __name__ == "__main__":
    tables = generate()
    write_csvs(tables, Path(__file__).parent / "synthetic")
    for name, df in tables.items():
        print(f"{name:18s} {len(df):6d} rows")
