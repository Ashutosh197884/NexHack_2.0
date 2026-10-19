"""QR API schemas — plan §8.1 request/response contracts."""
from __future__ import annotations

from pydantic import BaseModel, Field


class QrAnalyzeRequest(BaseModel):
    qr_payload: str = Field(min_length=1, max_length=2048,
                            description="Decoded QR text (a `upi://pay…` URI)")
    # If the user typed/selected a recipient and the QR disagrees, we surface
    # a RECIPIENT_MISMATCH warning (plan §6.2 `recipient_mismatch`).
    intended_recipient: str | None = Field(default=None, max_length=180)


class PaymentData(BaseModel):
    payee_vpa: str | None
    payee_name: str | None
    amount: float | None
    currency: str | None
    reference: str | None
    note: str | None


class QrAnalyzeResponse(BaseModel):
    valid: bool
    payment_data: PaymentData
    qrid: str | None = None
    errors: list[str] = []
    warnings: list[str] = []
    flags: dict[str, bool] = {}


class QrSampleOut(BaseModel):
    id: str
    label: str
    scenario: str
    payload: str
    rationale: str
