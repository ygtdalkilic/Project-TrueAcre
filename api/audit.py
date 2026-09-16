"""Audit log: every state-changing action and every look at grower evidence, with who, when,
and from which address. Written inside the same transaction as the action it describes.

Rows carry no foreign keys, so they survive the deletion of the user or company involved.
Admins read their company's log through /api/orgs/current/audit; account-level events
(sign-ins, account deletion) have no company and are kept for forensics only.
"""
import json

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import models
from api.security import client_ip

PAGE = 200  # most recent events returned


def record(db: Session, action: str, *, request: Request | None = None, user_id: int | None = None,
           org_id: int | None = None, **detail) -> None:
    db.add(models.AuditEvent(
        org_id=org_id, user_id=user_id, action=action,
        detail=json.dumps(detail, default=str) if detail else None,
        ip=client_ip(request) if request else None,
    ))


def events_for(db: Session, org_id: int) -> list[dict]:
    events = db.scalars(select(models.AuditEvent).where(models.AuditEvent.org_id == org_id)
                        .order_by(models.AuditEvent.id.desc()).limit(PAGE)).all()
    users = {u.id: u.email for u in db.scalars(select(models.User)).all()}
    return [
        {"id": e.id, "at": e.created_at.isoformat(), "action": e.action, "user_id": e.user_id,
         "user": users.get(e.user_id), "ip": e.ip, "detail": json.loads(e.detail) if e.detail else {}}
        for e in events
    ]
