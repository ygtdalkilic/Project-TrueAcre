"""Tables for accounts, companies, and each company's uploaded data.

A company (Organization) owns its datasets. A user belongs to companies through memberships
with a role. Invites let an admin add people by email before they have signed in.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, UniqueConstraint, delete
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from api.db import Base

ROLES = ("admin", "analyst")


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    picture: Mapped[str | None] = mapped_column(String(1000))
    session_version: Mapped[int] = mapped_column(default=1)  # bump it to sign the user out everywhere
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    data_version: Mapped[int] = mapped_column(default=0)  # bumped on every upload; keys the pipeline cache
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="organization")


class Membership(Base):
    __tablename__ = "memberships"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship(back_populates="memberships")


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (UniqueConstraint("org_id", "email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # null once that account is deleted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Dataset(Base):
    """One uploaded table for one company: the validated CSV, encrypted (see api/crypto.py)."""

    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("org_id", "table_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    table_name: Mapped[str] = mapped_column(String(40))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    row_count: Mapped[int]
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def purge_organization(db: Session, org_id: int) -> None:
    """Delete a company and everything it owns. Callers commit."""
    for model in (Dataset, Invite, Membership):
        db.execute(delete(model).where(model.org_id == org_id))
    db.execute(delete(Organization).where(Organization.id == org_id))
