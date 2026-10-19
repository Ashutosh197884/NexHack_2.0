"""Risk API schemas — plan §8.2/§8.5 contracts."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.schemas.qr import PaymentData


class SdkCaptureIn(BaseModel):
    """Optional device-side capture (derived features only, never raw streams)."""
    signals: dict[str, float] = {}
    detections: dict[str, bool] = {}


class RiskAssessRequest(BaseModel):
    payee_vpa: str = Field(min_length=3, max_length=180)
    payee_name: str | None = Field(default=None, max_length=180)
    amount: float = Field(gt=0, le=100_000_00)
    currency: str = Field(default="INR", pattern=r"^[A-Za-z]{3}$")
    transaction_hour: int | None = Field(default=None, ge=0, le=23)
    # Optional structured QR info (pre-analyzed via /qr/analyze)
    qr_payload: str | None = Field(default=None, max_length=2048)
    qr_flags: dict[str, bool] | None = None
    intended_recipient: str | None = Field(default=None, max_length=180)
    # optional real SDK capture; absent => behavioural axis stays neutral
    sdk_capture: SdkCaptureIn | None = None
    step: str = "initial"   # initial | challenge (two-round step-up)

    @field_validator("payee_vpa")
    @classmethod
    def _vpa_shape(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("payee_vpa must look like handle@psp")
        return v.strip()


class Reason(BaseModel):
    code: str
    severity: str
    message: str
    contribution: float | None = None


class RiskAssessResponse(BaseModel):
    assessment_id: str
    transaction_id: str
    payee_vpa: str
    payee_name: str | None
    amount: float
    currency: str
    risk_score: int
    risk_level: str
    action: str                  # approve | step_up | block
    reasons: list[Reason]
    recommendation: str
    probability: float
    profile_deviation: float
    transactional_signals: dict
    next_step_hint: str
    is_simulated: bool = True


class QrAnalyzeResultEmbedded(BaseModel):
    valid: bool
    payment_data: PaymentData


class ModelWeightsOut(BaseModel):
    version: str
    weights: list[dict]
