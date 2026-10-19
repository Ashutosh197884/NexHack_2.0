"""Audit-event recorder (plan §7 / §11): records actions without payment data."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditEvent


def log(db: Session, *, user_id: str | None, event_type: str,
        resource_id: str | None = None) -> None:
    db.add(AuditEvent(user_id=user_id, event_type=event_type, resource_id=resource_id))
