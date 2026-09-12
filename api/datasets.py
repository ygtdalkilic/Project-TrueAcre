"""Company data intake: CSV templates, validated uploads, one-click demo data, and status.

Each of the seven tables the engine needs is uploaded as a CSV. Columns and types come from the
row schemas in data/schemas.py, so the template, the validation, and the engine can never drift
apart. Extra columns are dropped; the normalized CSV is what gets stored.
"""
import io
import types
from dataclasses import fields
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import models
from api.auth import current_membership
from api.crypto import encrypt
from api.db import get_db
from api.security import RateLimiter
from api.tables import TABLES
from data.generate import DEFAULT_SEED, generate

router = APIRouter(prefix="/api/data", tags=["data"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ROWS = 500_000
UPLOAD_LIMIT = RateLimiter(limit=30, window_seconds=60)  # per user
TRUE_WORDS, FALSE_WORDS = {"true", "t", "yes", "y", "1"}, {"false", "f", "no", "n", "0"}


def _kind(annotation) -> tuple[str, bool]:
    """('int' | 'float' | 'bool' | 'str', optional?) for a schema field type."""
    optional = False
    if isinstance(annotation, types.UnionType):
        optional = type(None) in annotation.__args__
        annotation = next(a for a in annotation.__args__ if a is not type(None))
    return {int: "int", float: "float", bool: "bool"}.get(annotation, "str"), optional


def validate(table: str, csv_text: str) -> pd.DataFrame:
    """Parse and check one uploaded CSV. Raises HTTPException(400) with a message a person can act on."""
    row_type = TABLES[table]
    try:
        df = pd.read_csv(io.StringIO(csv_text), dtype=str, keep_default_na=False)
    except Exception as e:  # pandas raises several parser error types
        raise HTTPException(status_code=400, detail=f"could not parse CSV: {e}")
    if len(df) > MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"too many rows: {len(df)} (limit {MAX_ROWS})")

    missing = [f.name for f in fields(row_type) if f.name not in df.columns]
    if missing:
        raise HTTPException(status_code=400, detail=f"missing columns: {', '.join(missing)}")

    out = pd.DataFrame()
    for f in fields(row_type):
        kind, optional = _kind(f.type)
        col = df[f.name].str.strip()
        blank = col == ""
        if blank.any() and not optional:
            rows = (blank[blank].index[:5] + 2).tolist()  # +2: header line and 1-based numbering
            raise HTTPException(status_code=400, detail=f"column '{f.name}' has blank values (rows {rows})")
        if kind in ("int", "float"):
            numbers = pd.to_numeric(col.where(~blank), errors="coerce")
            bad = numbers.isna() & ~blank
            if bad.any():
                rows = (bad[bad].index[:5] + 2).tolist()
                raise HTTPException(status_code=400, detail=f"column '{f.name}' must be numeric (rows {rows})")
            out[f.name] = numbers.astype("Int64") if kind == "int" else numbers
        elif kind == "bool":
            lowered = col.str.lower()
            bad = ~lowered.isin(TRUE_WORDS | FALSE_WORDS)
            if bad.any():
                rows = (bad[bad].index[:5] + 2).tolist()
                raise HTTPException(status_code=400, detail=f"column '{f.name}' must be true/false (rows {rows})")
            out[f.name] = lowered.isin(TRUE_WORDS)
        else:
            out[f.name] = col.where(~blank, None) if optional else col
    return out


def _store(db: Session, org: models.Organization, table: str, df: pd.DataFrame, user_id: int | None) -> models.Dataset:
    ds = db.scalar(select(models.Dataset).where(models.Dataset.org_id == org.id, models.Dataset.table_name == table))
    if ds is None:
        ds = models.Dataset(org_id=org.id, table_name=table, ciphertext=b"", row_count=0)
        db.add(ds)
    ds.ciphertext, ds.row_count = encrypt(df.to_csv(index=False)), len(df)
    ds.uploaded_by, ds.uploaded_at = user_id, datetime.now(timezone.utc)
    org.data_version += 1
    return ds


def _table_or_404(table: str) -> None:
    if table not in TABLES:
        raise HTTPException(status_code=404, detail=f"unknown table; expected one of {list(TABLES)}")


@router.get("")
def status(membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)):
    present = {d.table_name: d for d in db.scalars(select(models.Dataset).where(models.Dataset.org_id == membership.org_id))}
    return [
        {"table": t, "columns": [f.name for f in fields(row_type)],
         "rows": present[t].row_count if t in present else None,
         "uploaded_at": present[t].uploaded_at.isoformat() if t in present else None}
        for t, row_type in TABLES.items()
    ]


@router.get("/templates/{table}.csv", response_class=PlainTextResponse)
def template(table: str, membership: models.Membership = Depends(current_membership)):
    _table_or_404(table)
    header = ",".join(f.name for f in fields(TABLES[table]))
    return PlainTextResponse(header + "\n", media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{table}.csv"'})


@router.put("/{table}")
async def upload(table: str, file: UploadFile, request: Request,
                 membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)):
    _table_or_404(table)
    UPLOAD_LIMIT.check(str(membership.user_id))
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"file larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="file must be UTF-8 text")
    df = validate(table, text)
    ds = _store(db, membership.organization, table, df, membership.user_id)
    db.commit()
    return {"table": table, "rows": ds.row_count, "uploaded_at": ds.uploaded_at.isoformat()}


@router.delete("/{table}", status_code=204)
def delete(table: str, membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)):
    _table_or_404(table)
    ds = db.scalar(select(models.Dataset).where(models.Dataset.org_id == membership.org_id,
                                                models.Dataset.table_name == table))
    if ds is None:
        raise HTTPException(status_code=404, detail="nothing uploaded for that table")
    db.delete(ds)
    membership.organization.data_version += 1
    db.commit()


@router.post("/demo")
def load_demo(membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)):
    """Replace the company's tables with the synthetic sample dataset."""
    tables = generate(seed=DEFAULT_SEED)
    for name in TABLES:
        _store(db, membership.organization, name, tables[name], membership.user_id)
    db.commit()
    return {"loaded": list(TABLES)}
