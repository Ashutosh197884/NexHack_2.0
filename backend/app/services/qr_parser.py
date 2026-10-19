"""UPI QR intelligence — parse and validate `upi://pay` payment URIs.

Security boundary (plan §6.1): a syntactically valid UPI address does NOT prove
the recipient is legitimate. This module validates structure and surfaces
warnings; trust decisions belong to the risk engine + the user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlsplit

# A VPA is `handle@psp` — letters/digits/.-_ around an alnum handle psp name.
VPA_RE = re.compile(r"^[A-Za-z0-9.\-_]{2,64}@[A-Za-z][A-Za-z0-9.\-]{1,32}$")
AMOUNT_RE = re.compile(r"^\d{1,9}(\.\d{1,2})?$")
SUPPORTED_SCHEME = "upi"
# Only `pay` is a static push-payment QR. Others are request/intent URIs.
SUPPORTED_ACTIONS = {"pay"}

_AMOUNT_KEYS = {"am", "amount"}
_NAME_KEYS = {"pn", "payeeName"}
_EXPECTED_KEYS = {
    "pa",  # payee address (required)
    "pn",  # payee name
    "am",  # amount
    "cu",  # currency
    "tr",  # transaction ref
    "tn",  # transaction note
    "mc",  # merchant code
    "mam",  # minimal amount
    "mode", "purpose", "qrMedium", "sign", "orgid", "mid",
}


@dataclass
class QrAnalysis:
    valid: bool
    payee_vpa: str | None = None
    payee_name: str | None = None
    amount: float | None = None
    currency: str | None = None
    reference: str | None = None
    note: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)

    def to_payment_data(self) -> dict:
        return {
            "payee_vpa": self.payee_vpa,
            "payee_name": self.payee_name,
            "amount": self.amount,
            "currency": self.currency,
            "reference": self.reference,
            "note": self.note,
        }


def parse_upi_uri(payload: str) -> QrAnalysis:
    """Decode + structurally validate a UPI payment URI (never trusts it)."""
    result = QrAnalysis(valid=False)
    payload = (payload or "").strip()
    if not payload:
        result.errors.append("EMPTY_PAYLOAD")
        return result
    if len(payload) > 2048:
        result.errors.append("PAYLOAD_TOO_LARGE")
        return result

    # some scanners percent-decode once too many; tolerate encoded scheme
    try:
        parts = urlsplit(payload)
    except ValueError:
        result.errors.append("MALFORMED_URI")
        return result

    if parts.scheme.lower() != SUPPORTED_SCHEME:
        result.errors.append(f"UNSUPPORTED_SCHEME:{parts.scheme or 'none'}")
        return result

    action = parts.netloc.lower() or parts.path.strip("/")
    if action not in SUPPORTED_ACTIONS:
        result.errors.append(f"UNSUPPORTED_ACTION:{action or 'none'}")
        return result

    params: dict[str, str] = {}
    try:
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            key = k.strip().lower()
            if key in params:
                result.errors.append(f"DUPLICATE_PARAM:{key}")
            params[key] = v
    except ValueError:
        result.errors.append("MALFORMED_QUERY")
        return result
    result.params = params

    payee_vpa = (params.get("pa") or "").strip()
    if not payee_vpa:
        result.errors.append("MISSING_PAYEE_ADDRESS")
    elif not VPA_RE.match(payee_vpa):
        result.errors.append("INVALID_PAYEE_ADDRESS")
    result.payee_vpa = payee_vpa or None

    raw_name = params.get("pn")
    if raw_name is not None:
        result.payee_name = unquote(raw_name).strip() or None

    raw_amount = params.get("am")
    if raw_amount not in (None, ""):
        if not AMOUNT_RE.match(raw_amount.strip()):
            result.errors.append("INVALID_AMOUNT")
        else:
            result.amount = float(raw_amount)
    else:
        result.warnings.append("QR_NO_EMBEDDED_AMOUNT")

    currency = (params.get("cu") or "").upper() or None
    result.currency = currency
    if currency and currency != "INR":
        result.errors.append(f"UNSUPPORTED_CURRENCY:{currency}")
    elif not currency and result.amount is not None:
        result.warnings.append("MISSING_CURRENCY")

    result.reference = params.get("tr") or None
    result.note = params.get("tn") or None

    unexpected = set(params) - _EXPECTED_KEYS
    if unexpected:
        result.warnings.append("UNEXPECTED_PARAMS:" + ",".join(sorted(unexpected)))

    amount = result.amount
    if amount is not None and amount == 0:
        result.warnings.append("ZERO_AMOUNT")

    result.valid = not result.errors
    result.flags = {
        "has_amount": amount is not None,
        "has_payee_name": result.payee_name is not None,
        "has_reference": result.reference is not None,
        "has_unexpected_params": bool(unexpected),
        "merchant_qr": bool(params.get("mc")),
    }
    return result
