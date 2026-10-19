"""Risk fusion service — the plan's §6 in code.

Two independent signal axes fused into one normalized 0–100 score:

1. Transactional axis (from the QR/payment request):
   new recipient, amount vs the user's own history, burst activity,
   malformed/ambiguous QR structure. Deterministic rules — always available.

2. Behavioural axis (the proven trained engine in `secureupi/risk_engine.py`):
   payment-interaction dynamics + device flags, when an SDK capture is
   supplied. Optional per plan §10: with no capture, behavioural features are
   frozen at the model's *benign* mean so lack of data stays risk-neutral.

The response shape is the plan's §8.4 contract: risk_score, risk_level,
reasons[{code, severity, message}], recommendation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ml import inference
from app.services import recipient_service

REASONING_LEVELS = {"low", "medium", "high"}


@dataclass
class SdkCapture:
    """Optional device-side capture (derived features only — never raw streams)."""
    signals: dict[str, float] = field(default_factory=dict)
    detections: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict | None) -> "SdkCapture":
        if not payload:
            return cls()
        return cls(
            signals={k: float(v) for k, v in (payload.get("signals") or {}).items()
                    if isinstance(v, (int, float))},
            detections={k: bool(v) for k, v in (payload.get("detections") or {}).items()},
        )


@dataclass
class Reason:
    code: str
    severity: str   # info | medium | high
    message: str
    contribution: float | None = None

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity,
                "message": self.message, "contribution": self.contribution}


@dataclass
class Assessment:
    risk_score: int
    risk_level: str           # low | medium | high (contract casing)
    action: str               # approve | step_up | block
    reasons: list[Reason]
    recommendation: str
    probability: float
    model_version: str
    step: str
    profile_deviation: float
    transactional_signals: dict
    is_simulated: bool = True

    def reasons_payload(self) -> list[dict]:
        return [r.as_dict() for r in self.reasons]


# What each behavioural feature means in plain language (contract messages).
_BEHAVIOURAL_MESSAGES: dict[str, str] = {
    "amount_log": "The payment amount is unusually large for your history.",
    "new_payee": "First payment to this payee.",
    "amount_fill_s": "The amount was entered slowly — pacing consistent with hesitation or waiting for instructions.",
    "amount_corrections": "The amount was corrected/re-typed multiple times.",
    "amount_max_pause_s": "A long pause occurred while entering the amount.",
    "pay_dwell_s": "An unusually long review time before pressing Pay was observed.",
    "pin_cps": "The UPI PIN was entered slower than your usual rhythm.",
    "pin_max_pause_s": "A long pause mid-PIN suggests the PIN may have been dictated.",
    "pin_resets": "The PIN pad was cleared and restarted — a stress signal.",
    "pin_hold_std_ms": "Uneven tap pressure/timing on the PIN pad (tremor/stress pattern).",
    "pin_tap_offset_px": "Tap accuracy dropped — hands shaking is a stress indicator.",
    "screen_share": "Screen-sharing / remote view was detected during the payment flow.",
    "integrity_fail": "Device integrity check failed (rooted device, emulator, or tampered app).",
}

_RULE_WEIGHTS = {
    "UNUSUAL_AMOUNT": 18,
    "BURST_ACTIVITY": 10,
    "LARGE_PERSONAL_TRANSFER": 22,
    "MISSING_MERCHANT_QR": 6,
}


class RiskService:
    """Stateless per-request service; groups via DI."""

    def __init__(self) -> None:
        self._engine = inference.get_engine()

    # ------------------------------------------------------------------
    def _build_vector(self, amount: float, sdk: SdkCapture) -> dict[str, float]:
        """Merge transactional context + optional behavioural capture.

        Missing behavioural keys are frozen at the model's benign mean so the
        behavioural axis is risk-neutral when nothing was captured.
        """
        benign = self._engine.model["benign_profile"]["mean"]
        vector: dict[str, float] = {k: float(v) for k, v in benign.items()}
        if amount > 0:
            real_ctx = {"amount_log": round(math.log10(max(amount, 1.0)), 4)}
        else:
            real_ctx = {}
        # real captured signals override the neutral freeze
        for k, v in sdk.signals.items():
            if k in benign:
                real_ctx[k] = v
        for flag, on in sdk.detections.items():
            if flag in ("screen_share", "integrity_fail"):
                real_ctx[flag] = 1.0 if on else 0.0
        vector.update(real_ctx)
        return vector

    # ------------------------------------------------------------------
    def _transactional_reasons(
        self, *, amount: float, is_new_recipient: bool, qr_flags: dict | None,
        user_txn_count_10m: int, user_avg_amount: float | None,
        sdk: SdkCapture,
    ) -> list[Reason]:
        reasons: list[Reason] = []

        if is_new_recipient:
            reasons.append(Reason(
                "NEW_RECIPIENT", "medium",
                "This recipient does not appear in your transaction history.",
            ))
        if amount and user_avg_amount and amount > max(5_000.0, 5 * user_avg_amount):
            reasons.append(Reason(
                "UNUSUAL_AMOUNT", "high",
                "The requested amount is significantly higher than your usual payments.",
                contribution=_RULE_WEIGHTS["UNUSUAL_AMOUNT"],
            ))
        if user_txn_count_10m >= 3:
            reasons.append(Reason(
                "BURST_ACTIVITY", "medium",
                f"{user_txn_count_10m} payments in a very short window — rapid repeated transfers.",
                contribution=_RULE_WEIGHTS["BURST_ACTIVITY"],
            ))

        non_merchant_amount = amount and amount >= 10_000
        looks_merchant = bool(qr_flags and qr_flags.get("merchant_qr"))
        if non_merchant_amount and not looks_merchant:
            reasons.append(Reason(
                "LARGE_PERSONAL_TRANSFER", "high",
                "A large amount requested via a personal (non-merchant) QR.",
                contribution=_RULE_WEIGHTS["LARGE_PERSONAL_TRANSFER"],
            ))
        if qr_flags and qr_flags.get("has_unexpected_params"):
            reasons.append(Reason(
                "SUSPICIOUS_QR_STRUCTURE", "medium",
                "The QR contains unexpected parameters — possible tampering or a templated fake QR.",
                contribution=_RULE_WEIGHTS["MISSING_MERCHANT_QR"] + 12,
            ))
        return reasons

    # ------------------------------------------------------------------
    def assess(
        self, db: Session, *, user_id: str, amount: float, currency: str,
        payee_vpa: str, payee_name: str | None, qr_flags: dict | None = None,
        sdk: SdkCapture | None = None, step: str = "initial",
        known_recipient: bool | None = None,
    ) -> Assessment:
        sdk = sdk or SdkCapture()
        engine = self._engine
        model = engine.model

        if known_recipient is None:
            if db is None:
                # Direct (unit-test) call without persistence: caller must say
                # whether the payee is known — never guess from a null session.
                raise ValueError("known_recipient must be given when db is None")
            recipient = recipient_service.lookup(db, user_id=user_id,
                                                 payee_vpa=payee_vpa)
            known_recipient = recipient is not None
        is_new_recipient = not known_recipient
        if db is not None:
            stats = recipient_service.user_txn_window_stats(db, user_id=user_id)
        else:
            stats = {"recent_10m_count": 0, "avg_amount": None}
        in_seq_count = stats["recent_10m_count"]

        vector = self._build_vector(amount, sdk)
        result = engine.evaluate(vector, step=step, amount=amount)

        # ---- fuse: transactional rules + behavioural engine ----
        reasons: list[Reason] = self._transactional_reasons(
            amount=amount, is_new_recipient=is_new_recipient,
            qr_flags=qr_flags, user_txn_count_10m=in_seq_count,
            user_avg_amount=stats["avg_amount"], sdk=sdk,
        )
        # behavioural engine contributions, mapped to contract messages
        for c in result.get("top_contributors", []):
            code = c["key"].upper()
            share = float(c.get("share") or 0.0)
            reasons.append(Reason(
                code=code,
                severity="high" if share >= 30 else ("medium" if share >= 15 else "info"),
                message=_BEHAVIOURAL_MESSAGES.get(c["key"], c["label"]),
                contribution=round(share, 1),
            ))
        # QR / context rules above feed the score purely through the contract;
        # reflect them in the score so the number is honest about all axes.
        rule_points = sum((r.contribution or 0) for r in reasons
                          if r.code in _RULE_WEIGHTS)
        fused_score = min(100, max(int(result["risk_score"]), 0) + int(rule_points))

        if step == "challenge":
            action = result["action"].lower().replace("-", "_")
        else:
            # rules can escalate the level; recompute from fused score using engine cuts
            policy = result["policy_config"]
            if fused_score < policy["low_max"]:
                level = "low"
            elif fused_score < policy["medium_max"]:
                level = "medium"
            else:
                level = "high"
            action = {"low": "approve", "medium": "step_up", "high": "step_up"}[level]

        if action == "approve":
            recommendation = "Risk signals are within your normal behaviour. You can proceed."
        elif action == "step_up":
            recommendation = ("Verify the recipient and amount before continuing — step-up authentication is required.")
        else:
            recommendation = "Strong risk indicators present — cancel the payment and report the QR."

        return Assessment(
            risk_score=fused_score,
            risk_level=level,
            action=action,
            reasons=reasons,
            recommendation=recommendation,
            probability=result.get("probability", 0.0),
            model_version=str(model.get("version", "unknown")),
            step=step,
            profile_deviation=result.get("profile_deviation", 0.0),
            transactional_signals={
                "is_new_recipient": is_new_recipient,
                "recent_10m_count": in_seq_count,
                "avg_amount": stats["avg_amount"],
                "qr_flags": qr_flags or {},
                "sdk_capture": bool(sdk.signals or sdk.detections),
            },
        )


def get_risk_service() -> RiskService:
    return RiskService()
