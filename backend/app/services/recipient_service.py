"""Recipient registry + per-user behavioural statistics (server-derived only).

The backend must derive trusted features (plan §8.5) from records here, never
from client claims. `avg_amount` / `recent_10m_count` come from the user's own
`transactions` rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Recipient, Transaction, utcnow


def recipient_lookup(db: Session, *, user_id: str, payee_vpa: str) -> Recipient | None:
    return lookup(db, user_id=user_id, payee_vpa=payee_vpa)


def lookup(db: Session, *, user_id: str, payee_vpa: str) -> Recipient | None:
    return db.scalar(
        select(Recipient).where(
            Recipient.user_id == user_id,
            func.lower(Recipient.payee_vpa) == payee_vpa.lower(),
        )
    )


def get_or_create(
    db: Session, *, user_id: str, payee_vpa: str, display_name: str | None = None
) -> tuple[Recipient, bool]:
    """Returns (recipient, created). Touches last_seen when it already exists."""
    rec = lookup(db, user_id=user_id, payee_vpa=payee_vpa)
    if rec is None:
        rec = Recipient(
            user_id=user_id, payee_vpa=payee_vpa, display_name=display_name
        )
        db.add(rec)
        db.flush()
        return rec, True
    rec.last_seen_at = utcnow()
    if display_name and not rec.display_name:
        rec.display_name = display_name
    return rec, False


def known_vpas(db: Session, *, user_id: str) -> set[str]:
    rows = db.scalars(select(Recipient.payee_vpa).where(Recipient.user_id == user_id))
    return {v.lower() for v in rows}


def user_txn_window_stats(db: Session, *, user_id: str) -> dict:
    """Stats the rule engine needs: recent burst count + lifetime average amount."""
    now = datetime.now(timezone.utc)
    ten_min_ago = now - timedelta(minutes=10)
    recent = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.transaction_time >= ten_min_ago,
        )
    ) or 0
    avg_amount = db.scalar(
        select(func.avg(Transaction.amount)).where(Transaction.user_id == user_id)
    )
    return {
        "recent_10m_count": int(recent),
        "avg_amount": float(avg_amount) if avg_amount is not None else None,
    }


def record_tx_results(db: Session, *, txn: Transaction, score: int, level: str,
                      status: str) -> None:
    txn.risk_score = score
    txn.risk_level = level
    txn.status = status
