"""Synthetic QR samples + rendering.

The MVP's scan path (per plan decision): demo generates QR images; the student
/org runs them through a scanner or the browser canvas + jsQR decode path.
No camera required, no native QR dependencies server-side (segno is pure
Python). Each sample has a deterministic id so tests and the demo are stable.
"""
from __future__ import annotations

import segno
from pydantic import BaseModel

from app.services.qr_parser import parse_upi_uri


class QrSample(BaseModel):
    id: str
    label: str
    scenario: str          # benign | suspicious | malformed
    payload: str
    rationale: str


_SAMPLES: list[QrSample] = [
    QrSample(
        id="coffee-shop",
        label="Coffee House — ₹250",
        scenario="benign",
        payload="upi://pay?pa=coffeehouse@upi&pn=Coffee%20House&am=250&cu=INR",
        rationale="Typical merchant payment: known payee, small amount.",
    ),
    QrSample(
        id="grocery",
        label="Grocery Store — ₹1,240",
        scenario="benign",
        payload="upi://pay?pa=groceryshop@icici&pn=Green%20Basket&am=1240&cu=INR&tr=ORD90412",
        rationale="Payment with a transaction reference — regular recurring merchant.",
    ),
    QrSample(
        id="vpa-verified",
        label="Namma Metro card top-up — ₹500",
        scenario="benign",
        payload="upi://pay?pa=metrotopup@upi&pn=Namma%20Metro&am=500&cu=INR&mc=5411",
        rationale="Merchant-code QR (mc present) — typical transit top-up.",
    ),
    QrSample(
        id="suspicious-personal",
        label="Big amount to a personal VPA — ₹48,000",
        scenario="suspicious",
        payload="upi://pay?pa=quickhelp99@ybl&pn=Quick%20Help&am=48000&cu=INR",
        rationale="Large transfer to a personal (non-merchant) VPA — classic social-engineering pattern.",
    ),
    QrSample(
        id="suspicious-scam",
        label="\u201cVerify your account\u201d scam QR — ₹499",
        scenario="suspicious",
        payload="upi://pay?pa=paytm-verify@paytm&pn=Account%20Verification%20Desk&am=499&cu=INR&tn=KYC%20verification%20fee",
        rationale="Small amount but urgent-sounding note; impersonation-style payee name.",
    ),
    QrSample(
        id="mismatch-demo",
        label="Display-name mismatch demo",
        scenario="suspicious",
        payload="upi://pay?pa=charityhelp@upi&pn=Official%20Relief%20Fund&am=2000&cu=INR",
        rationale="Use with `intended_recipient` set differently in /qr/analyze to trigger a recipient-mismatch warning.",
    ),
    QrSample(
        id="no-amount",
        label="Merchant QR without an amount",
        scenario="benign",
        payload="upi://pay?pa=streetvendor@upi&pn=Street%20Vendor&cu=INR",
        rationale="Valid QR, but the payee lets you choose the amount — extra care typing it.",
    ),
    QrSample(
        id="malformed-amount",
        label="Malformed amount — parse failure",
        scenario="malformed",
        payload="upi://pay?pa=shop@upi&am=4..50&cu=INR",
        rationale="Amount is not a valid decimal — the endpoint must reject, not silently pay.",
    ),
    QrSample(
        id="unknown-scheme",
        label="Unsupported scheme",
        scenario="malformed",
        payload="https://example.com/pay?to=someone",
        rationale="Non-UPI QR (e.g. a website link) — must never be treated as a payment.",
    ),
    QrSample(
        id="dup-param",
        label="Duplicate / conflicting params",
        scenario="malformed",
        payload="upi://pay?pa=a@upi&pa=b@upi&am=100&am=999&cu=INR",
        rationale="Payee address given twice with different values — tampering signal.",
    ),
]

_BY_ID = {s.id: s for s in _SAMPLES}


def sample_by_id(sample_id: str) -> QrSample | None:
    return _BY_ID.get(sample_id)


def all_samples() -> list[QrSample]:
    return list(_SAMPLES)


def render_svg_png(sample_id: str) -> str:
    """Render a sample QR to SVG (scalable, no binary deps)."""
    s = _BY_ID.get(sample_id)
    if s is None:
        raise KeyError(sample_id)
    return segno.make(s.payload, error="m").svg_inline(
        scale=8, border=2, dark="#111827", light="#ffffff"
    )
