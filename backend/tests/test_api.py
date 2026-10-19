"""API and security integration tests (§12 API/security tests) + the full
vertical slice: analyze → assess → simulate/cancel."""
from __future__ import annotations

from app.services.qr_generator import sample_by_id


def test_health_open(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["ml_ok"] is True


def test_sample_gallery_and_image(client):
    r = client.get("/api/v1/qr/samples")
    assert r.status_code == 200
    samples = r.json()
    assert len(samples) >= 8
    sid = samples[0]["id"]
    img = client.get(f"/api/v1/qr/samples/{sid}/image.svg")
    assert img.status_code == 200
    assert img.headers["content-type"].startswith("image/svg")
    assert b"<svg" in img.content


def test_qr_analyze_valid(client):
    s = sample_by_id("coffee-shop")
    r = client.post("/api/v1/qr/analyze", json={"qr_payload": s.payload})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["payment_data"]["payee_vpa"] == "coffeehouse@upi"


def test_qr_analyze_mismatch_warning(client):
    s = sample_by_id("mismatch-demo")
    r = client.post("/api/v1/qr/analyze", json={
        "qr_payload": s.payload,
        "intended_recipient": "someoneelse@upi",
    })
    assert r.status_code == 200
    assert any(w.startswith("RECIPIENT_MISMATCH") for w in r.json()["warnings"])


def test_qr_analyze_rejects_malformed(client):
    s = sample_by_id("unknown-scheme")
    r = client.post("/api/v1/qr/analyze", json={"qr_payload": s.payload})
    assert r.status_code == 200  # analyze is a reporting endpoint, not an error
    body = r.json()
    assert body["valid"] is False
    assert body["errors"]


# ---- auth & security boundaries ----

def test_protected_endpoint_requires_token(client):
    r = client.get("/api/v1/transactions")
    assert r.status_code == 401
    r = client.get("/api/v1/dashboard/summary")
    assert r.status_code == 401


def test_invalid_token_rejected(client):
    r = client.get("/api/v1/transactions",
                   headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_register_and_me(client):
    r = client.post("/api/v1/auth/register", json={
        "name": "Second User", "email": "second@secureupi.app",
        "password": "second-pass-1"})
    assert r.status_code == 201
    tok = r.json()["access_token"]
    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200
    assert me.json()["email"] == "second@secureupi.app"


def test_register_duplicate_email(client):
    r = client.post("/api/v1/auth/register", json={
        "name": "Dup", "email": "second@secureupi.app",
        "password": "second-pass-1"})
    assert r.status_code == 409


def test_register_bad_email_rejected(client):
    r = client.post("/api/v1/auth/register", json={
        "name": "x", "email": "not-an-email", "password": "second-pass-1"})
    assert r.status_code == 422


def test_weak_password_rejected(client):
    r = client.post("/api/v1/auth/register", json={
        "name": "x", "email": "weak@secureupi.app", "password": "short"})
    assert r.status_code == 422


# ---- the vertical slice ----

def _assess(client, header, **overrides) -> dict:
    payload = {
        "payee_vpa": "coffeehouse@upi",
        "payee_name": "Coffee House",
        "amount": 250.0,
        "currency": "INR",
        "qr_payload": sample_by_id("coffee-shop").payload,
        "sdk_capture": {"signals": {
            "amount_fill_s": 1.2, "amount_corrections": 0,
            "amount_max_pause_s": 0.2, "pay_dwell_s": 0.8,
            "pin_cps": 4.5, "pin_max_pause_s": 0.15, "pin_resets": 0,
            "pin_hold_std_ms": 20.0, "pin_tap_offset_px": 4.0,
        }},
    }
    payload.update(overrides)
    r = client.post("/api/v1/risk/assess", json=payload, headers=header)
    assert r.status_code == 200, r.text
    return r.json()


def test_full_flow_low_risk_approve(client, auth_header):
    a = _assess(client, auth_header)
    assert a["risk_level"] == "low"
    assert a["action"] == "approve"
    assert a["risk_score"] < 20
    # simulate
    r = client.post(f"/api/v1/transactions/{a['transaction_id']}/simulate",
                    json={"user_decision": "confirm"}, headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "SIMULATED_SUCCESS"
    assert "No money was transferred" in body["message"]

    # history + detail
    lst = client.get("/api/v1/transactions", headers=auth_header)
    assert any(t["id"] == a["transaction_id"] for t in lst.json())
    det = client.get(f"/api/v1/transactions/{a['transaction_id']}",
                     headers=auth_header)
    assert det.status_code == 200
    factors = det.json()["assessment"]["factors"]
    assert factors  # at least one recorded reason


def test_full_flow_suspicious_block(client, auth_header):
    a = _assess(client, auth_header,
                payee_vpa="quickhelp99@ybl", payee_name="Quick Help",
                amount=48_000.0,
                qr_payload=None,
                sdk_capture=None)
    assert a["risk_level"] in {"medium", "high"}
    if a["risk_level"] == "high":
        r = client.post(f"/api/v1/transactions/{a['transaction_id']}/simulate",
                        json={"user_decision": "confirm"}, headers=auth_header)
        assert r.status_code == 200
        assert r.json()["status"] == "SIMULATED_FAILURE"


def test_second_assessment_of_same_payee_not_new(client, auth_header):
    # unique payee => first assessment is first-ever, second is not
    a1 = _assess(client, auth_header, payee_vpa="freshpayee@upi",
                 payee_name=None, amount=260.0, qr_payload=None)
    a2 = _assess(client, auth_header, payee_vpa="freshpayee@upi",
                 payee_name=None, amount=270.0, qr_payload=None)
    assert a1["transactional_signals"]["is_new_recipient"] is True
    assert a2["transactional_signals"]["is_new_recipient"] is False


def test_assess_rejects_bad_vpa(client, auth_header):
    r = client.post("/api/v1/risk/assess", json={
        "payee_vpa": "no-at-sign", "amount": 10.0}, headers=auth_header)
    assert r.status_code == 422


def test_assess_rejects_malformed_qr(client, auth_header):
    r = client.post("/api/v1/risk/assess", json={
        "payee_vpa": "x@upi", "amount": 10.0,
        "qr_payload": "https://evil.com"
    }, headers=auth_header)
    assert r.status_code == 400


def test_cancel_flow(client, auth_header):
    a = _assess(client, auth_header, amount=310.0)
    r = client.post(f"/api/v1/transactions/{a['transaction_id']}/cancel",
                    headers=auth_header)
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"
    # double-cancel -> 409
    r2 = client.post(f"/api/v1/transactions/{a['transaction_id']}/cancel",
                     headers=auth_header)
    assert r2.status_code == 409


def test_ownership_isolation(client, auth_header):
    """Users cannot touch each other's transactions (§11 authorization)."""
    a = _assess(client, auth_header, amount=320.0)
    # second user
    r = client.post("/api/v1/auth/register", json={
        "name": "Other", "email": "other@secureupi.app",
        "password": "other-pass-1"})
    tok2 = r.json()["access_token"]
    r2 = client.post(f"/api/v1/transactions/{a['transaction_id']}/simulate",
                     json={"user_decision": "confirm"},
                     headers={"Authorization": f"Bearer {tok2}"})
    assert r2.status_code == 404
