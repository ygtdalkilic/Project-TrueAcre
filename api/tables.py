"""The seven tables a company uploads, mapped to their row schemas.

Kept in its own module so both the intake code and the pipeline can import it without
depending on each other.
"""
from data import schemas

TABLES = {  # upload name -> row schema
    "growers": schemas.Grower,
    "dealers": schemas.Dealer,
    "varieties": schemas.Variety,
    "seed_purchases": schemas.SeedPurchase,
    "acreage_reports": schemas.AcreageReport,
    "elevator_receipts": schemas.ElevatorReceipt,
    "county_yields": schemas.CountyYield,
}
