"""Row schemas for the input tables and the synthetic ground truth.

Each dataclass is one row. Tables are pandas DataFrames built from lists of rows.

Only seed purchases carry grower_id, because they are the seed company's own customer records.
Acreage reports and elevator receipts come from outside and identify the grower only by name,
county, and (acreage only) a farm number. engine/resolve.py attaches grower_id to them.
"""
from dataclasses import dataclass, fields


@dataclass
class Grower:
    grower_id: str
    name: str
    county: str
    state: str
    farm_number: str | None  # FSA farm number, when the company has it on file


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
    operator_name: str  # as written on the government form
    farm_number: str
    county: str
    state: str
    season: int
    crop: str
    acres: float


@dataclass
class ElevatorReceipt:
    receipt_id: str
    seller_name: str  # as written on the scale ticket
    county: str
    state: str
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
class SeedStatement:
    """The grower's own statement of acres planted with seed NOT bought from this company: another
    company's seed or conventional seed. 0 means every acre of the crop was this company's seed.
    Optional table; without a statement, an acre gap cannot be told apart from another brand's seed."""
    grower_id: str
    season: int
    crop: str
    other_seed_acres: float


@dataclass
class GroundTruth:
    grower_id: str
    season: int
    case_type: str  # "clean" | "ghost_seed" | "split_brand" | "missing_dealer" | "neighbor_dealer"
    planted_acres: float  # what the grower really planted
    licensed_acres: float  # acres the seed they really bought could plant
    hidden_units: int  # units bought from a non-participating dealer, invisible to the system
    other_seed_acres: float  # acres planted with another company's seed (split_brand only)


@dataclass
class RecordLink:
    """Ground truth: which grower an external record (acreage report or elevator receipt) really belongs to."""
    record_id: str
    grower_id: str


def columns(row_type) -> list[str]:
    return [f.name for f in fields(row_type)]
