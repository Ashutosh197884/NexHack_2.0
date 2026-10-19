"""First-boot seed data: demo users + known recipients + light history.

Seeded only if the users table is empty, and only when seed_demo_users=True.
The demo credentials are (capitalised names for the UI):

    demo@secureupi.app / "secureupi-demo"        (Aarav Sharma — fast typist)
    senior@secureupi.app / "secureupi-demo"      (Ramesh Gupta — senior, slow & smooth)

Both get a couple of known recipients and a couple of settled historical
transactions, so "new_recipient" and "avg_amount" rules have something to
compare against; no PIN/personal secrets involved.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Recipient, Transaction, User, utcnow

DEMO_PASSWORD_HINT = "secureupi-demo"


def seed_if_empty(db: Session, *, enabled: bool, demo_password: str) -> None:
    if not enabled or db.scalar(select(func.count()).select_from(User)):
        return
    for name, email, recipients, hist_txns in [
        ("Aarav Sharma", "demo@secureupi.app",
         ["Coffee House", "Green Basket"],
         [("Coffee House", 250.0, "coffeehouse@upi"),
          ("Green Basket", 1180.0, "groceryshop@icici")]),
        ("Ramesh Gupta", "senior@secureupi.app",
         ["Namma Metro"],
         [("Namma Metro", 500.0, "metrotopup@upi")]),
    ]:
        user = User(name=name, email=email, password_hash=hash_password(demo_password))
        db.add(user)
        db.flush()
        for label, amount, vpa in hist_txns:
            rec, _ = _get_or_create_recipient(db, user, vpa, label)
            db.add(Transaction(user_id=user.id, recipient_id=rec.id,
                               payee_vpa=vpa, payee_name=label, amount=amount,
                               currency="INR"))
        db.commit()


def _get_or_create_recipient(db: Session, user: User, vpa: str,
                             label: str) -> tuple[Recipient, bool]:
    rec = db.scalar(
        select(Recipient).where(
            Recipient.user_id == user.id, Recipient.payee_vpa == vpa))
    if rec is None:
        rec = Recipient(user_id=user.id, payee_vpa=vpa, display_name=label)
        db.add(rec)
        db.flush()
        return rec, True
    return rec, False
