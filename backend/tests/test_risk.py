"""Risk fusion engine tests (§12 risk-engine tests)."""
from __future__ import annotations

from app.services.risk_engine import Reason, RiskService, SdkCapture


def svc() -> RiskService:
    return RiskService()


def test_engine_loads():
    s = svc()
    assert s._engine.model["version"]


def test_malformed_qr_never_scored_perfectly_normal():
    """A malformed QR must not be treated as a normal transaction with a low
    score (plan §6.3). At the API layer it's a 400; here assert QR flags feed
    reasons when supplied as suspicious structure."""
    from app.services.risk_engine import RiskService

    result = RiskService()._transactional_reasons(
        amount=100.0, is_new_recipient=False,
        qr_flags={"has_unexpected_params": True, "merchant_qr": False},
        user_txn_count_10m=0, user_avg_amount=100.0, sdk=SdkCapture(),
    )
    assert any(r.code == "SUSPICIOUS_QR_STRUCTURE" for r in result)


def test_typical_known_recipient_low_risk():
    # calm behavioural capture + known recipient + small amount
    sdk = SdkCapture(signals={
        "amount_fill_s": 1.2, "amount_corrections": 0,
        "amount_max_pause_s": 0.2, "pay_dwell_s": 0.8,
        "pin_cps": 4.5, "pin_max_pause_s": 0.15, "pin_resets": 0,
        "pin_hold_std_ms": 20.0, "pin_tap_offset_px": 4.0,
    })
    a = svc().assess(None, user_id="u", amount=250.0, currency="INR",
                     payee_vpa="coffeehouse@upi", payee_name="Coffee House",
                     qr_flags={"merchant_qr": True}, sdk=sdk, step="initial",
                     known_recipient=True)
    assert a.risk_score < 20        # calm + known + small = low
    assert a.risk_level == "low"
    assert a.action == "approve"
    assert all(r.severity in {"medium", "info"} for r in a.reasons)


def test_new_recipient_large_amount_medium_or_high():
    sdk = SdkCapture()   # no behavioural capture — neutral
    a = svc().assess(None, user_id="u", amount=48_000.0, currency="INR",
                     payee_vpa="quickhelp99@ybl", payee_name="Quick Help",
                     qr_flags={"merchant_qr": False}, sdk=sdk,
                     known_recipient=False)
    assert a.risk_level in {"medium", "high"}
    codes = {r.code for r in a.reasons}
    assert "NEW_RECIPIENT" in codes
    assert "LARGE_PERSONAL_TRANSFER" in codes


def test_rules_can_escalate_but_never_fabricate_levels():
    a = svc().assess(None, user_id="u", amount=300.0, currency="INR",
                     payee_vpa="known@upi", payee_name=None,
                     qr_flags={"merchant_qr": True}, sdk=SdkCapture(signals={
                         "pin_max_pause_s": 40.0,  # frantic-looking PIN
                     }), known_recipient=True)
    # even with rule boosts, level/action stay in the contract's enums
    assert a.risk_level in {"low", "medium", "high"}
    assert a.action in {"approve", "step_up", "block"}


def test_device_flags_surface_reasons():
    sdk = SdkCapture(detections={"screen_share": True})
    a = svc().assess(None, user_id="u", amount=500.0, currency="INR",
                     payee_vpa="x@upi", payee_name=None, qr_flags={},
                     sdk=sdk, known_recipient=True)
    codes = {r.code for r in a.reasons}
    assert "SCREEN_SHARE" in codes


def test_no_sdk_capture_stays_neutral():
    """Behavioural axis absent = benign-freeze, never fabricated high risk (§10)."""
    a = svc().assess(None, user_id="u", amount=1_000.0, currency="INR",
                     payee_vpa="x@upi", payee_name=None,
                     qr_flags={"merchant_qr": True}, sdk=None,
                     known_recipient=True)
    assert a.risk_level in {"low", "medium"}
    assert not any(r.code in {"PIN_CPS", "PIN_MAX_PAUSE_S"} for r in a.reasons)


def test_reasons_contract():
    r = Reason("NEW_RECIPIENT", "medium", "test")
    d = r.as_dict()
    assert set(d) == {"code", "severity", "message", "contribution"}
