"""Companies, members, and invites."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import audit, models, pipeline
from api.auth import current_membership, current_user, me_payload, normalize_email, require_admin, set_session
from api.db import get_db

router = APIRouter(prefix="/api/orgs", tags=["orgs"])
MAX_NAME = 200


class NewOrg(BaseModel):
    name: str


class NewInvite(BaseModel):
    email: str
    role: str = "analyst"
    grower_id: str | None = None  # required for role 'grower': the grower record this person is


def _check_name(name: str) -> str:
    name = " ".join(name.split())
    if not name or len(name) > MAX_NAME:
        raise HTTPException(status_code=400, detail=f"company name must be 1 to {MAX_NAME} characters")
    return name


@router.post("", status_code=201)
def create_org(body: NewOrg, request: Request, response: Response, user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    org = models.Organization(name=_check_name(body.name))
    db.add(org)
    db.flush()
    db.add(models.Membership(user_id=user.id, org_id=org.id, role="admin"))
    audit.record(db, "org.create", request=request, user_id=user.id, org_id=org.id, name=org.name)
    db.commit()
    set_session(response, user, org.id)
    return me_payload(db, user, org.id)


@router.delete("/current", status_code=204)
def delete_org(request: Request, response: Response, membership: models.Membership = Depends(require_admin),
               db: Session = Depends(get_db)):
    """Delete the company and every dataset, invite, and membership it owns. Admins only."""
    user, org_id, name = membership.user, membership.org_id, membership.organization.name
    models.purge_organization(db, org_id)
    audit.record(db, "org.delete", request=request, user_id=user.id, org_id=org_id, name=name)
    db.commit()
    pipeline.forget(org_id)
    set_session(response, user, None)


@router.get("/current/audit")
def audit_log(membership: models.Membership = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    """The company's most recent audit events. Admins only."""
    return audit.events_for(db, membership.org_id)


@router.get("/current/members")
def list_members(membership: models.Membership = Depends(current_membership), db: Session = Depends(get_db)):
    members = db.scalars(select(models.Membership).where(models.Membership.org_id == membership.org_id)).all()
    out = {"members": [{"user_id": m.user_id, "email": m.user.email, "name": m.user.name, "role": m.role,
                        "grower_id": m.grower_id} for m in members]}
    if membership.role == "admin":
        pending = db.scalars(select(models.Invite).where(models.Invite.org_id == membership.org_id,
                                                         models.Invite.accepted_at.is_(None))).all()
        out["invites"] = [{"id": i.id, "email": i.email, "role": i.role, "grower_id": i.grower_id} for i in pending]
    return out


def _check_grower(db: Session, org: models.Organization, role: str, grower_id: str | None) -> str | None:
    """A grower invite must name a grower in the company's uploaded growers table; staff invites must not."""
    if role != "grower":
        if grower_id:
            raise HTTPException(status_code=400, detail="only grower invites take a grower_id")
        return None
    if not grower_id:
        raise HTTPException(status_code=400, detail="a grower invite needs the grower_id it belongs to")
    growers = pipeline.load_tables(db, org).get("growers")
    if growers is None or grower_id not in set(growers["grower_id"]):
        raise HTTPException(status_code=404, detail="no grower with that grower_id in this company's data")
    return grower_id


@router.post("/current/invites", status_code=201)
def invite(body: NewInvite, request: Request, membership: models.Membership = Depends(require_admin),
           db: Session = Depends(get_db)):
    if body.role not in models.ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {list(models.ROLES)}")
    email = normalize_email(body.email)
    grower_id = _check_grower(db, membership.organization, body.role, body.grower_id)

    existing_user = db.scalar(select(models.User).where(models.User.email == email))
    if existing_user and db.get(models.Membership, (existing_user.id, membership.org_id)):
        raise HTTPException(status_code=409, detail="already a member")

    inv = db.scalar(select(models.Invite).where(models.Invite.org_id == membership.org_id,
                                                models.Invite.email == email))
    if inv is None:
        inv = models.Invite(org_id=membership.org_id, email=email, role=body.role, grower_id=grower_id,
                            invited_by=membership.user_id)
        db.add(inv)
    else:
        inv.role, inv.grower_id, inv.accepted_at = body.role, grower_id, None

    if existing_user:  # they already have an account: no need to wait for their next sign-in
        db.add(models.Membership(user_id=existing_user.id, org_id=membership.org_id, role=body.role,
                                 grower_id=grower_id))
        inv.accepted_at = datetime.now(timezone.utc)
    audit.record(db, "invite.create", request=request, user_id=membership.user_id, org_id=membership.org_id,
                 email=email, role=body.role, grower_id=grower_id, joined=existing_user is not None)
    db.commit()
    return {"email": email, "role": body.role, "grower_id": grower_id, "joined": existing_user is not None}


@router.delete("/current/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: int, request: Request, membership: models.Membership = Depends(require_admin),
                  db: Session = Depends(get_db)):
    inv = db.get(models.Invite, invite_id)
    if inv is None or inv.org_id != membership.org_id or inv.accepted_at is not None:
        raise HTTPException(status_code=404, detail="no such pending invite")
    audit.record(db, "invite.revoke", request=request, user_id=membership.user_id, org_id=membership.org_id,
                 email=inv.email)
    db.delete(inv)
    db.commit()


@router.delete("/current/members/{user_id}", status_code=204)
def remove_member(user_id: int, request: Request, membership: models.Membership = Depends(require_admin),
                  db: Session = Depends(get_db)):
    target = db.get(models.Membership, (user_id, membership.org_id))
    if target is None:
        raise HTTPException(status_code=404, detail="not a member")
    admins = db.scalars(select(models.Membership).where(models.Membership.org_id == membership.org_id,
                                                        models.Membership.role == "admin")).all()
    if target.role == "admin" and len(admins) == 1:
        raise HTTPException(status_code=409, detail="a company needs at least one admin")
    audit.record(db, "member.remove", request=request, user_id=membership.user_id, org_id=membership.org_id,
                 removed_user_id=user_id, email=target.user.email)
    db.delete(target)
    db.commit()
