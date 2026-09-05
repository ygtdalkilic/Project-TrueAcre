"""Row schemas for the input tables and the synthetic ground truth.

Each dataclass is one row. Tables are pandas DataFrames built from lists of rows.
"""
from dataclasses import dataclass, fields


@dataclass
class Grower:
    grower_id: str
    name: str
    county: str
    state: str


@dataclass
class Dealer:
    dealer_id: str
    name: str
    county: str
    state: str
    participating: bool  # True if this dealer reports its receipts into the system


@dataclass
class Variety:
    variety_id: str
    name: str
    crop: str
    seeds_per_unit: int  # seeds in one purchased unit (bag)
    target_seeds_per_acre: int  # recommended seeding rate


@dataclass
class SeedPurchase:
    purchase_id: str
    grower_id: str
    dealer_id: str
    variety_id: str
    season: int
    units: int


@dataclass
class AcreageReport:
    report_id: str
    grower_id: str
    season: int
    crop: str
    acres: float


@dataclass
class ElevatorReceipt:
    receipt_id: str
    grower_id: str
    elevator_id: str
    season: int
    crop: str
    bushels: float


@dataclass
class CountyYield:
    county: str
    state: str
    season: int
    crop: str
    mean_yield: float  # bushels per acre
    std_yield: float


@dataclass
class GroundTruth:
    grower_id: str
    season: int
    case_type: str  # "clean" | "ghost_seed" | "missing_dealer"
    planted_acres: float  # what the grower really planted
    licensed_acres: float  # acres the seed they really bought could plant
    hidden_units: int  # units bought from a non-participating dealer, invisible to the system


def columns(row_type) -> list[str]:
    return [f.name for f in fields(row_type)]
