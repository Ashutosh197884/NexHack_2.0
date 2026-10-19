"""Dashboard summary (§8.6) — risk distribution + top reason codes."""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import RiskAssessment, RiskFactor, Transaction, User
from app.schemas.transactions import DashboardSummary, TransactionOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary(db: Session = Depends(get_db),
            user: User = Depends(get_current_user)) -> DashboardSummary:
    base = select(Transaction).where(Transaction.user_id == user.id)
    rows = db.scalars(base).all()
    by_status: Counter = Counter(r.status for r in rows)
    level_counts: Counter = Counter(
        (r.risk_level or "unknown").lower() for r in rows if r.risk_score is not None
    )
    recent = list(db.scalars(
        base.order_by(Transaction.transaction_time.desc()).limit(10)
    ))

    # top reason codes across this user's assessments
    factor_counts = db.execute(
        select(RiskFactor.factor_code, func.count())
        .join(RiskAssessment, RiskFactor.assessment_id == RiskAssessment.id)
        .join(Transaction, RiskAssessment.transaction_id == Transaction.id)
        .where(Transaction.user_id == user.id)
        .group_by(RiskFactor.factor_code)
        .order_by(func.count().desc())
        .limit(6)
    ).all()

    return DashboardSummary(
        analyzed=by_status.get("ANALYZED", 0),
        cancelled=by_status.get("CANCELLED", 0),
        simulated_success=by_status.get("SIMULATED_SUCCESS", 0),
        simulated_failure=by_status.get("SIMULATED_FAILURE", 0),
        risk_levels=dict(level_counts),
        top_reason_codes=[
            {"code": code, "count": count} for code, count in factor_counts
        ],
        recent=[TransactionOut.model_validate(t, from_attributes=True)
                for t in recent],
    )
