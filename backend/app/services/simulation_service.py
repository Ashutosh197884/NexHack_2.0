"""Simulated payment execution.

The plan is explicit (§11): *never represent a simulated payment as a real
transfer*. Statuses here (ANALYZED / CANCELLED / SIMULATED_SUCCESS /
SIMULATED_FAILURE) must not be confused with banking settlement, and responses
carry that disclaimer.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, utcnow
from app.services import audit

def evaluate_flow_policy(
    txn: Transaction, assessment_action: str
) -> str:
    """Which next step the API offers. `block` must stop the simulate path."""
    if assessment_action == "block":
        return "block"
    return "allow"



def load_for_user(db: Session, *, txn_id: str, user_id: str) -> Transaction | None:
    return db.scalar(
        select(Transaction).where(
            Transaction.id == txn_id, Transaction.user_id == user_id
        )
    )


def mark_cancelled(db: Session, txn: Transaction) -> Transaction:
    txn.status = "CANCELLED"
    txn.simulated_at = utcnow()
    audit.log(db, user_id=txn.user_id, event_type="TXN_CANCELLED",
              resource_id=txn.id)
    return txn


def run_simulated(db: Session, txn: Transaction,
                  *, assessment_action: str) -> tuple[Transaction, str]:
    """Execute the demo payment. Returns (transaction, message)."""
    if assessment_action == "block":
        # policy prevents reaching the switch for blocked flows (clearly demo)
        txn.status = "SIMULATED_FAILURE"
        txn.simulated_at = utcnow()
        message = ("Demo payment NOT simulated — risk policy would block this "
                   "before authorization. No money was transferred.")
    else:
        txn.status = "SIMULATED_SUCCESS"
        txn.simulated_at = utcnow()
        message = ("Demo payment simulated successfully. No money was transferred.")
    audit.log(db, user_id=txn.user_id,
              event_type="TXN_SIMULATED", resource_id=txn.id)
    return txn, message
