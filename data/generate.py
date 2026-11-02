"""Synthetic data generator with seeded ghost-seed cases as ground truth.

Crop is soybeans only. Every grower is honest ("clean") unless designated:
  ghost_seed      buys licensed seed for the first season, then buys for only part of the
                  acreage and plants the rest with saved seed (the first season is recorded as clean)
  split_brand     honest, but plants part of the acreage with another company's seed, which
                  this company never sees a receipt for
  missing_dealer  honest, but part of the seed came from a dealer that does not report
                  into the system, so those receipts are invisible
  neighbor_dealer the same, but the non-reporting dealer is across the line in a bordering
                  county, while every dealer in the grower's own county reports

Ghost-seed and split-brand growers are placed where every dealer in the county and in the
counties bordering it participates: in purchases, acreage, and deliveries they look the same.
Neighbor-dealer growers are placed in fully reporting counties that border a non-reporting
dealer, and missing-dealer growers in counties with one, so every outcome is tested.

Most grower-seasons (STATEMENT_SHARE) have a seed statement on file. Split-brand growers state
their other-seed acres truthfully; ghost-seed growers state 0, since saved seed is what they hide.

External records (acreage reports, elevator receipts) do not carry grower_id. They carry
the grower's name as someone else wrote it (see _name_variant) plus county and, for acreage,
the FSA farm number. The record_links table is the ground truth for engine/resolve.py.

Run `python -m data.generate` to write CSVs to data/synthetic/.
"""
from __future__ import annotations

import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from data.geography import neighbors, place
from data.schemas import (
    AcreageReport,
    CountyYield,
    Dealer,
    ElevatorReceipt,
    GroundTruth,
    Grower,
    RecordLink,
    SeedPurchase,
    SeedStatement,
    Variety,
    columns,
)

CROP = "soybeans"
SEEDS_PER_UNIT = 140_000  # one soybean seed unit (bag) holds 140,000 seeds
DEFAULT_SEED = 42  # RNG seed for the default dataset used by the API and the CLI
DEFAULT_OUT_DIR = Path(__file__).parent / "synthetic"  # where `python -m data.generate` writes CSVs
REGISTERED_FARM_SHARE = 0.7  # share of growers whose FSA farm number the seed company already has on file
STATEMENT_SHARE = 0.8  # share of grower-seasons with a seed statement (other-seed acres) on file

# county, state, do all dealers report into the system, typical yield (bu/acre)
COUNTIES = [
    ("Story", "IA", True, 58.0),
    ("Boone", "IA", True, 56.0),
    ("McLean", "IL", True, 62.0),
    ("Champaign", "IL", True, 61.0),
    ("Wright", "IA", False, 54.0),
    ("Livingston", "IL", False, 59.0),
    ("Boone", "IL", False, 60.0),  # same name as Boone, IA: county names are only unique within a state
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
# Elevators also take grain from people who are not this company's customers. Their tickets have no
# owner in the registry and must never be linked to one. Surnames are chosen to resemble none above.
# How third parties write a name: NAME_VARIANT_KINDS equally likely kinds, the first VERBATIM_NAME_KINDS
# exact, then upper case, "Last, First", a middle initial, a "Farms" suffix, and a one-letter typo.
NAME_VARIANT_KINDS = 10
VERBATIM_NAME_KINDS = 5
OTHER_SELLERS_PER_COUNTY = 2
OTHER_LAST_NAMES = ["Novak", "Dvorak", "Kowalczyk", "Lindqvist", "Okafor", "Ramirez", "Nguyen", "Yamamoto"]

DEFAULT_GROWERS = 200  # growers in the default dataset (demo, CLI, validation report)
DEFAULT_SEASONS = (2024, 2025)

# How the synthetic world behaves. Each range is (low, high): a uniform draw, or an inclusive count.
FARM_ACRES = (100, 1500)  # a farm's planted acreage, drawn in steps of ACRE_STEP
ACRE_STEP = 5
PLANTED_DRIFT = (0.95, 1.05)  # a farm's acreage from one season to the next
REPORTING_JITTER = (0.99, 1.01)  # acres declared on the government form versus acres really planted
OVERBUY = (1.0, 1.05)  # seed bought versus seed needed: growers round up
VARIETIES_PER_GROWER = (1, 3)
GHOST_BOUGHT_SHARE = (0.2, 0.6)  # share of the acreage a replanting grower still buys licensed seed for
SPLIT_BRAND_OTHER_SHARE = (0.3, 0.7)  # share a split-brand grower plants with another company's seed
HIDDEN_PURCHASE_SHARE = (0.4, 0.8)  # share of seed bought from a dealer that does not report
COUNTY_YIELD_NOISE = 2.0  # bu/acre: standard deviation of a season's county mean around its typical yield
COUNTY_YIELD_STD = (5.0, 7.0)  # bu/acre: spread of grower yields within a county-season
MIN_YIELD = 15.0  # bu/acre: floor for a disastrous season
DELIVERED_SHARE = (0.9, 1.0)  # share of the harvest that reaches an elevator in the data
ELEVATORS_PER_GROWER = (1, 2)
NON_CUSTOMER_YIELD_FACTOR = (0.8, 1.1)  # a non-customer's yield relative to the county's typical yield


def _frame(rows, row_type) -> pd.DataFrame:
    return pd.DataFrame([asdict(r) for r in rows], columns=columns(row_type))


def _farm_acres(rng: np.random.Generator) -> int:
    """A farm's acreage: FARM_ACRES, in steps of ACRE_STEP."""
    return int(rng.integers(FARM_ACRES[0] // ACRE_STEP, FARM_ACRES[1] // ACRE_STEP + 1)) * ACRE_STEP


def _name_variant(name: str, rng: np.random.Generator) -> str:
    """One plausible way the same person is written on an external record."""
    first, last = name.split(" ")
    kind = int(rng.integers(0, NAME_VARIANT_KINDS))
    if kind < VERBATIM_NAME_KINDS:
        return name
    if kind == 5:
        return name.upper()
    if kind == 6:
        return f"{last}, {first}"
    if kind == 7:
        return f"{first} {chr(65 + int(rng.integers(26)))}. {last}"
    if kind == 8:
        return f"{name} Farms"
    i = int(rng.integers(1, len(name)))  # typo: drop one letter, never the first
    while name[i] == " ":
        i = int(rng.integers(1, len(name)))
    return name[:i] + name[i + 1:]


def generate(
    n_growers: int = DEFAULT_GROWERS,
    seasons: tuple[int, ...] = DEFAULT_SEASONS,
    n_ghost: int = 10,
    n_missing_dealer: int = 10,
    seed: int = DEFAULT_SEED,
    messy_names: bool = True,
    n_split_brand: int = 10,
    n_neighbor_dealer: int = 6,
) -> dict[str, pd.DataFrame]:
    """Build every table. `messy_names=False` writes registry names verbatim on external records,
    which makes every record resolvable and gives tests exact expectations."""
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
                    round(base + rng.normal(0, COUNTY_YIELD_NOISE), 1), round(rng.uniform(*COUNTY_YIELD_STD), 1))
        for county, state, _, base in COUNTIES
        for season in seasons
    ]
    yield_lookup = {(y.county, y.state, y.season): y for y in county_yields}

    county_idx = rng.integers(0, len(COUNTIES), size=n_growers)
    growers: list[Grower] = []
    true_farm: list[str] = []  # every grower has an FSA farm number; the registry only knows some of them
    used_names: set[tuple[str, int]] = set()
    farms_in_county = [0] * len(COUNTIES)
    for i, c in enumerate(county_idx):
        while True:  # registry names are unique within a county
            name = f"{FIRST_NAMES[rng.integers(len(FIRST_NAMES))]} {LAST_NAMES[rng.integers(len(LAST_NAMES))]}"
            if (name, c) not in used_names:
                break
        used_names.add((name, c))
        farms_in_county[c] += 1  # FSA numbers farms per county office, so the same number recurs in other counties
        farm = f"{farms_in_county[c]}"
        true_farm.append(farm)
        registered = farm if rng.random() < REGISTERED_FARM_SHARE else None
        growers.append(Grower(f"G{i + 1:04d}", name, COUNTIES[c][0], COUNTIES[c][1], registered))

    keys = [place(county, state) for county, state, _, _ in COUNTIES]
    own_full = [full for _, _, full, _ in COUNTIES]
    area_full = [  # every dealer in this county and in the listed counties bordering it reports
        all(own_full[k] for k in range(len(COUNTIES)) if k == c or keys[k] in neighbors().get(keys[c], ()))
        for c in range(len(COUNTIES))
    ]
    full_cov = [i for i, c in enumerate(county_idx) if area_full[c]]
    edge_cov = [i for i, c in enumerate(county_idx) if own_full[c] and not area_full[c]]
    partial_cov = [i for i, c in enumerate(county_idx) if not own_full[c]]
    if (n_ghost + n_split_brand > len(full_cov) or n_neighbor_dealer > len(edge_cov)
            or n_missing_dealer > len(partial_cov)):
        raise ValueError("not enough growers in the right counties for the requested case counts")
    case_type = ["clean"] * n_growers
    full_picks = rng.choice(full_cov, size=n_ghost + n_split_brand, replace=False)
    for i in full_picks[:n_ghost]:
        case_type[i] = "ghost_seed"
    for i in full_picks[n_ghost:]:
        case_type[i] = "split_brand"
    for i in rng.choice(edge_cov, size=n_neighbor_dealer, replace=False):
        case_type[i] = "neighbor_dealer"
    for i in rng.choice(partial_cov, size=n_missing_dealer, replace=False):
        case_type[i] = "missing_dealer"

    purchases: list[SeedPurchase] = []
    statements: list[SeedStatement] = []
    reports: list[AcreageReport] = []
    receipts: list[ElevatorReceipt] = []
    truth: list[GroundTruth] = []
    links: list[RecordLink] = []

    for i, (g, grower_type) in enumerate(zip(growers, case_type)):
        visible_dealers = [d for d in dealers if (d.county, d.state) == (g.county, g.state) and d.participating]
        farm_size = _farm_acres(rng)
        for season_no, season in enumerate(seasons):
            # A ghost-seed grower buys licensed seed once, then replants saved seed in the seasons after.
            ctype = "clean" if grower_type == "ghost_seed" and season_no == 0 else grower_type
            planted = float(round(farm_size * rng.uniform(*PLANTED_DRIFT) / ACRE_STEP) * ACRE_STEP)
            other_acres = float(round(planted * rng.uniform(*SPLIT_BRAND_OTHER_SHARE))) if ctype == "split_brand" else 0.0
            seed_acres = (planted - other_acres) * (rng.uniform(*GHOST_BOUGHT_SHARE) if ctype == "ghost_seed" else 1.0)
            hidden_frac = (rng.uniform(*HIDDEN_PURCHASE_SHARE) if ctype in ("missing_dealer", "neighbor_dealer")
                           else 0.0)

            k = int(rng.integers(VARIETIES_PER_GROWER[0], VARIETIES_PER_GROWER[1] + 1))
            chosen = [varieties[i] for i in rng.choice(len(varieties), size=k, replace=False)]
            licensed = 0.0
            hidden_units = 0
            for v in chosen:
                overbuy = rng.uniform(*OVERBUY)
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

            if rng.random() < STATEMENT_SHARE:
                statements.append(SeedStatement(g.grower_id, season, CROP, other_acres))

            report_id = f"A{len(reports) + 1:05d}"
            reports.append(
                AcreageReport(report_id, _name_variant(g.name, rng) if messy_names else g.name, true_farm[i],
                              g.county, g.state, season, CROP, round(planted * rng.uniform(*REPORTING_JITTER), 1))
            )
            links.append(RecordLink(report_id, g.grower_id))

            cy = yield_lookup[(g.county, g.state, season)]
            realized_yield = max(MIN_YIELD, rng.normal(cy.mean_yield, cy.std_yield))
            bushels = planted * realized_yield * rng.uniform(*DELIVERED_SHARE)
            n_elevators = int(rng.integers(ELEVATORS_PER_GROWER[0], ELEVATORS_PER_GROWER[1] + 1))
            for e, share in enumerate(rng.dirichlet(np.ones(n_elevators))):
                receipt_id = f"R{len(receipts) + 1:05d}"
                receipts.append(
                    ElevatorReceipt(receipt_id, _name_variant(g.name, rng) if messy_names else g.name, g.county,
                                    g.state, f"E-{g.county}-{g.state}-{e + 1}", season, CROP, float(round(bushels * share)))
                )
                links.append(RecordLink(receipt_id, g.grower_id))

            truth.append(GroundTruth(g.grower_id, season, ctype, planted, round(licensed, 1), hidden_units, other_acres))

    for county, state, _, base in COUNTIES:  # non-customers: no record_links row, because they have no owner
        sellers = [f"{FIRST_NAMES[rng.integers(len(FIRST_NAMES))]} {OTHER_LAST_NAMES[rng.integers(len(OTHER_LAST_NAMES))]}"
                   for _ in range(OTHER_SELLERS_PER_COUNTY)]
        for season in seasons:
            for seller in sellers:
                receipts.append(ElevatorReceipt(f"R{len(receipts) + 1:05d}", seller, county, state,
                                                f"E-{county}-{state}-1", season, CROP,
                                                float(round(_farm_acres(rng) * base * rng.uniform(*NON_CUSTOMER_YIELD_FACTOR)))))

    return {
        "growers": _frame(growers, Grower),
        "dealers": _frame(dealers, Dealer),
        "varieties": _frame(varieties, Variety),
        "seed_purchases": _frame(purchases, SeedPurchase),
        "seed_statements": _frame(statements, SeedStatement),
        "acreage_reports": _frame(reports, AcreageReport),
        "elevator_receipts": _frame(receipts, ElevatorReceipt),
        "county_yields": _frame(county_yields, CountyYield),
        "ground_truth": _frame(truth, GroundTruth),
        "record_links": _frame(links, RecordLink),
    }


def write_csvs(tables: dict[str, pd.DataFrame], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)


def load_csvs(in_dir: Path) -> dict[str, pd.DataFrame]:
    """Read every CSV in `in_dir` back into a table keyed by file stem."""
    return {path.stem: pd.read_csv(path) for path in sorted(in_dir.glob("*.csv"))}


if __name__ == "__main__":
    tables = generate()
    write_csvs(tables, DEFAULT_OUT_DIR)
    for name, df in tables.items():
        print(f"{name:18s} {len(df):6d} rows")
