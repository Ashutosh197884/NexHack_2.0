"""Risk assessment endpoint — the plan's §8.2 contract."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import RiskAssessment, RiskFactor, Transaction, utcnow, User
from app.schemas.risk import RiskAssessRequest, RiskAssessResponse, SdkCaptureIn
from app.services import recipient_service
from app.services.qr_parser import parse_upi_uri
from app.services.risk_engine import RiskService, SdkCapture

router = APIRouter(prefix="/risk", tags=["risk"])


def _service(db: Session) -> RiskService:
    # A fresh service per request keeps engine state hot but simple.
    return RiskService()


def _next_hint(action: str) -> str:
    return {
        "approve": "Low risk — you may proceed or cancel.",
        "step_up": "Elevated risk — confirm, or cancel. Step-up re-authentication will be requested.",
        "block": "High risk — cancelling is strongly advised; this flow will not be simulated.",
    }[action]


@router.post("/assess", response_model=RiskAssessResponse)
def assess(
    body: RiskAssessRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RiskAssessResponse:
    service = _service(db)

    is_challenge = body.step == "challenge"
    if body.step not in ("initial", "challenge"):
        raise HTTPException(422, detail={"error": "step must be initial|challenge"})

    # ---- optional QR re-validation on the server (never trust the client) ----
    qr_flags: dict[str, bool] | None = body.qr_flags
    if body.qr_payload:
        parsed = parse_upi_uri(body.qr_payload)
        if not parsed.valid:
            raise HTTPException(400, detail={"error": "invalid QR payload",
                                             "errors": parsed.errors})
        if parsed.payee_vpa and parsed.payee_vpa.lower() != body.payee_vpa.lower():
            raise HTTPException(400, detail={
                "error": "payee_vpa does not match the QR payload",
            })
        if parsed.flags:
            qr_flags = parsed.flags

    # ---- server-side context: recipient registry, txn window, average ----
    # lookup BEFORE any registry write, so a first-ever payee is not mistaken
    # for a known one by the time scoring runs.
    rec_before = recipient_service.recipient_lookup(db, user_id=user.id,
                                                   payee_vpa=body.payee_vpa)
    is_new = rec_before is None
    rec, _created = recipient_service.get_or_create(
        db, user_id=user.id, payee_vpa=body.payee_vpa,
        display_name=body.payee_name,
    )
    stats = recipient_service.user_txn_window_stats(db, user_id=user.id)

    sdk = SdkCapture(
        signals=body.sdk_capture.signals if body.sdk_capture else {},
        detections=body.sdk_capture.detections if body.sdk_capture else {},
    )

    result = service.assess(
        db, user_id=user.id, amount=body.amount, currency=body.currency.upper(),
        payee_vpa=body.payee_vpa, payee_name=body.payee_name, qr_flags=qr_flags,
        sdk=sdk, step=body.step, known_recipient=(not is_new),
    )
    result.transactional_signals["is_new_recipient"] = is_new

    # ---- persist: transaction + assessment + factors (§7 schema) ----
    txn = Transaction(
        user_id=user.id, recipient_id=rec.id, payee_vpa=body.payee_vpa,
        payee_name=body.payee_name, amount=body.amount,
        currency=body.currency.upper(), risk_score=result.risk_score,
        risk_level=result.risk_level, status="ANALYZED",
    )
    db.add(txn)
    db.flush()

    assessment = RiskAssessment(
        transaction_id=txn.id, model_version=result.model_version,
        risk_score=result.risk_score, risk_level=result.risk_level,
        recommendation=result.recommendation,
    )
    db.add(assessment)
    db.flush()
    for r in result.reasons_payload():
        db.add(RiskFactor(
            assessment_id=assessment.id, factor_code=r["code"],
            severity=r["severity"], description=r["message"],
            contribution=r.get("contribution"),
        ))

    from app.services import audit as audit_svc
    audit_svc.log(db, user_id=user.id, event_type="ASSESSMENT_RUN",
                  resource_id=txn.id)
    db.commit()

    return RiskAssessResponse(
        assessment_id=assessment.id,
        transaction_id=txn.id,
        payee_vpa=body.payee_vpa,
        payee_name=body.payee_name,
        amount=body.amount,
        currency=body.currency.upper(),
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        action=result.action,
        reasons=result.reasons_payload(),
        recommendation=result.recommendation,
        probability=result.probability,
        profile_deviation=result.profile_deviation,
        transactional_signals=result.transactional_signals,
        next_step_hint=_next_hint(result.action),
        is_simulated=True,
    )
