"""Transactions endpoints (§8.3) — list, detail, cancel, simulate."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import RiskAssessment, Transaction, User
from app.schemas.transactions import (
    SimulateRequest, SimulateResponse, TransactionDetailOut, TransactionOut,
)
from app.services.simulation_service import mark_cancelled, run_simulated

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
) -> list[TransactionOut]:
    rows = db.scalars(
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.transaction_time.desc())
        .offset(offset).limit(limit)
    )
    return [TransactionOut.model_validate(t) for t in rows]


@router.get("/{txn_id}", response_model=TransactionDetailOut)
def get_transaction(
    txn_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TransactionDetailOut:
    txn = db.scalar(
        select(Transaction)
        .options(joinedload(Transaction.assessment)
                 .joinedload(RiskAssessment.factors))
        .where(Transaction.id == txn_id, Transaction.user_id == user.id)
    )
    if txn is None:
        raise HTTPException(404, detail={"error": "transaction not found"})
    return TransactionDetailOut.model_validate(txn, from_attributes=True)


@router.post("/{txn_id}/cancel", response_model=TransactionOut)
def cancel(
    txn_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TransactionOut:
    txn = _owned(db, txn_id, user.id)
    if txn.status not in ("ANALYZED", "SIMULATED_FAILURE"):
        raise HTTPException(409, detail={
            "error": f"cannot cancel a transaction in status {txn.status}"})
    mark_cancelled(db, txn)
    db.commit()
    return TransactionOut.model_validate(txn, from_attributes=True)


@router.post("/{txn_id}/simulate", response_model=SimulateResponse)
def simulate(
    txn_id: str,
    body: SimulateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SimulateResponse:
    if body.user_decision != "confirm":
        raise HTTPException(400, detail={
            "error": "user_decision must be 'confirm' (use /cancel to abort)"})
    txn = _owned(db, txn_id, user.id)
    if txn.status != "ANALYZED":
        raise HTTPException(409, detail={
            "error": f"transaction already in status {txn.status}"})
    assessment = txn.assessment
    action = _action_for(assessment) if assessment else "approve"
    txn, message = run_simulated(db, txn, assessment_action=action)
    db.commit()
    return SimulateResponse(transaction_id=txn.id, status=txn.status,
                            message=message)


def _action_for(assessment) -> str:
    """Model the action that was decided at assessment time (approve/step_up/block)."""
    level = (assessment.risk_level or "low").lower()
    if level == "high":
        return "block"
    if level == "medium":
        return "step_up"
    return "approve"


def _owned(db: Session, txn_id: str, user_id: str) -> Transaction:
    txn = db.scalar(
        select(Transaction).where(Transaction.id == txn_id,
                                  Transaction.user_id == user_id)
    )
    if txn is None:
        raise HTTPException(404, detail={"error": "transaction not found"})
    return txn
