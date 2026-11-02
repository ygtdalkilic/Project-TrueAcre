"""Sign-in and sessions.

Google sign-in: the browser obtains an ID token from Google Identity Services and posts it here.
The token's signature, audience (our client ID), issuer, and expiry are checked against Google's
public keys before anything is trusted. Users are created on their first verified sign-in, and
any pending invites for their email become memberships.

Sessions: a signed, HttpOnly, SameSite=Lax cookie carrying the user id, the chosen company, and
the user's session version. Bumping the version signs the user out everywhere.

Dev login exists only when TRUEACRE_DEV_LOGIN=1 and the server is not in production, so the app
can be used locally without a Google client ID.
"""
import os
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from api import audit, models, pipeline
from api.db import get_db
from api.security import IS_PRODUCTION, RateLimiter, client_ip

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
DEV_LOGIN = os.environ.get("TRUEACRE_DEV_LOGIN") == "1" and not IS_PRODUCTION
SESSION_SECRET = os.environ.get("SESSION_SECRET") or (None if IS_PRODUCTION else secrets.token_urlsafe(32))
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET must be set in production")

SESSION_COOKIE = "trueacre_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # seconds; static on purpose: the privacy page promises "up to seven days"
LOGIN_LIMIT = RateLimiter(limit=int(os.environ.get("TRUEACRE_LOGIN_LIMIT", "10")), window_seconds=60)  # per IP per minute
# Domain labels exclude the dot, so a failing match is linear; overlapping groups backtrack quadratically (ReDoS).
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")

router = APIRouter(prefix="/api", tags=["auth"])
_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="session")


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > models.EMAIL_LENGTH or not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="that is not a valid email address")
    return email


def verify_google_token(credential: str) -> dict:
    """Return Google's verified claims (sub, email, name, picture). Raises ValueError if invalid."""
    claims = id_token.verify_oauth2_token(credential, google_requests.Request(), GOOGLE_CLIENT_ID)
    if not claims.get("email_verified"):
        raise ValueError("Google has not verified this email address")
    return claims


def set_session(response: Response, user: models.User, org_id: int | None) -> None:
    token = _serializer.dumps({"uid": user.id, "org": org_id, "sv": user.session_version})
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_MAX_AGE, httponly=True,
                        secure=IS_PRODUCTION, samesite="lax", path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def read_session(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:  # includes expiry
        return None


def current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    data = read_session(request)
    user = db.get(models.User, data["uid"]) if data else None
    if user is None or user.session_version != data.get("sv"):
        raise HTTPException(status_code=401, detail="sign in required")
    request.state.session = data
    return user


def any_membership(request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(current_user)) -> models.Membership:
    org_id = request.state.session.get("org")
    membership = db.get(models.Membership, (user.id, org_id)) if org_id else None
    if membership is None:
        raise HTTPException(status_code=403, detail="choose a company first")
    return membership


def current_membership(membership: models.Membership = Depends(any_membership)) -> models.Membership:
    """Company staff only. Every company-wide route depends on this, so a grower is refused by default."""
    if membership.role not in models.STAFF_ROLES:
        raise HTTPException(status_code=403, detail="company staff only")
    return membership


def current_grower(membership: models.Membership = Depends(any_membership)) -> models.Membership:
    """A grower member, always linked to exactly one grower record."""
    if membership.role != "grower" or not membership.grower_id:
        raise HTTPException(status_code=403, detail="growers only")
    return membership


def require_admin(membership: models.Membership = Depends(current_membership)) -> models.Membership:
    if membership.role != "admin":
        raise HTTPException(status_code=403, detail="admins only")
    return membership


def _sign_in(db: Session, response: Response, request: Request, method: str, *, email: str, name: str,
             google_sub: str | None = None, picture: str | None = None) -> dict:
    user = None
    if google_sub:
        user = db.scalar(select(models.User).where(models.User.google_sub == google_sub))
    if user is None:
        user = db.scalar(select(models.User).where(models.User.email == email))
    if user is None:
        user = models.User(email=email, name=name, google_sub=google_sub, picture=picture)
        db.add(user)
    else:
        user.name, user.picture = name, picture or user.picture
        if google_sub and not user.google_sub:
            user.google_sub = google_sub
    db.flush()

    for invite in db.scalars(select(models.Invite).where(models.Invite.email == email,
                                                         models.Invite.accepted_at.is_(None))):
        if db.get(models.Membership, (user.id, invite.org_id)) is None:
            db.add(models.Membership(user_id=user.id, org_id=invite.org_id, role=invite.role, grower_id=invite.grower_id))
            audit.record(db, "invite.accept", request=request, user_id=user.id, org_id=invite.org_id, email=email)
        invite.accepted_at = datetime.now(timezone.utc)
    audit.record(db, "auth.sign_in", request=request, user_id=user.id, method=method, email=email)
    db.commit()

    memberships = db.scalars(select(models.Membership).where(models.Membership.user_id == user.id)).all()
    org_id = memberships[0].org_id if len(memberships) == 1 else None
    set_session(response, user, org_id)
    return me_payload(db, user, org_id)


def me_payload(db: Session, user: models.User, org_id: int | None) -> dict:
    memberships = db.scalars(select(models.Membership).where(models.Membership.user_id == user.id)).all()
    orgs = [{"id": m.org_id, "name": m.organization.name, "role": m.role, "grower_id": m.grower_id} for m in memberships]
    current = next((o for o in orgs if o["id"] == org_id), None)
    return {
        "user": {"id": user.id, "email": user.email, "name": user.name, "picture": user.picture},
        "organizations": orgs,
        "current_org": current,
    }


class GoogleCredential(BaseModel):
    credential: str


class DevLogin(BaseModel):
    email: str
    name: str = ""


@router.post("/auth/google")
def google_login(body: GoogleCredential, request: Request, response: Response, db: Session = Depends(get_db)):
    LOGIN_LIMIT.check(client_ip(request))
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on this server")
    try:
        claims = verify_google_token(body.credential)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"Google sign-in failed: {e}")
    email = normalize_email(claims["email"])
    return _sign_in(db, response, request, "google", email=email, name=claims.get("name") or email,
                    google_sub=claims["sub"], picture=claims.get("picture"))


@router.post("/auth/dev")
def dev_login(body: DevLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    if not DEV_LOGIN:
        raise HTTPException(status_code=404)
    LOGIN_LIMIT.check(client_ip(request))
    email = normalize_email(body.email)
    return _sign_in(db, response, request, "dev", email=email, name=body.name.strip() or email)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, user: models.User = Depends(current_user)):
    clear_session(response)


@router.post("/auth/logout-all", status_code=204)
def logout_everywhere(request: Request, response: Response, user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    user.session_version += 1
    audit.record(db, "auth.logout_all", request=request, user_id=user.id)
    db.commit()
    clear_session(response)


@router.get("/me")
def me(request: Request, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    return me_payload(db, user, request.state.session.get("org"))


@router.delete("/me", status_code=204)
def delete_account(request: Request, response: Response, user: models.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Delete the account. Companies where this user is the only member are deleted with it;
    where they are the only admin among other members, they must hand over admin first."""
    memberships = db.scalars(select(models.Membership).where(models.Membership.user_id == user.id)).all()
    for m in memberships:
        others = db.scalars(select(models.Membership).where(models.Membership.org_id == m.org_id,
                                                            models.Membership.user_id != user.id)).all()
        if not others:
            models.purge_organization(db, m.org_id)
            pipeline.forget(m.org_id)
        elif m.role == "admin" and not any(o.role == "admin" for o in others):
            raise HTTPException(status_code=409,
                                detail=f"make another member admin of {m.organization.name} before deleting your account")
    db.execute(delete(models.Membership).where(models.Membership.user_id == user.id))
    db.execute(update(models.Invite).where(models.Invite.invited_by == user.id).values(invited_by=None))
    db.execute(update(models.Dataset).where(models.Dataset.uploaded_by == user.id).values(uploaded_by=None))
    db.execute(update(models.LinkDecision).where(models.LinkDecision.decided_by == user.id).values(decided_by=None))
    db.execute(update(models.GrowerStatement).where(models.GrowerStatement.submitted_by == user.id)
               .values(submitted_by=None))
    audit.record(db, "account.delete", request=request, user_id=user.id, email=user.email)
    db.delete(user)
    db.commit()
    clear_session(response)


class OrgChoice(BaseModel):
    org_id: int


@router.put("/me/org")
def choose_org(body: OrgChoice, response: Response, user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    if db.get(models.Membership, (user.id, body.org_id)) is None:
        raise HTTPException(status_code=403, detail="you are not a member of that company")
    set_session(response, user, body.org_id)
    return me_payload(db, user, body.org_id)
