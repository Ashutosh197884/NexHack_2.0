"""Auth + transaction + dashboard schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---- auth ----
class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


# ---- transactions ----
class TransactionOut(BaseModel):
    id: str
    payee_vpa: str
    payee_name: str | None
    amount: float
    currency: str
    transaction_time: datetime
    risk_score: int | None
    risk_level: str | None
    status: str
    simulated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TransactionDetailOut(TransactionOut):
    assessment: "AssessmentEmbed | None" = None


class AssessmentEmbed(BaseModel):
    id: str
    model_version: str
    risk_score: int
    risk_level: str
    recommendation: str | None
    created_at: datetime
    factors: list["RiskFactorOut"]

    model_config = ConfigDict(from_attributes=True)


class RiskFactorOut(BaseModel):
    factor_code: str
    severity: str
    description: str
    contribution: float | None

    model_config = ConfigDict(from_attributes=True)


class SimulateRequest(BaseModel):
    user_decision: str = Field(pattern="^(confirm|cancel)$")


class SimulateResponse(BaseModel):
    transaction_id: str
    status: str
    message: str


# ---- dashboard ----
class DashboardSummary(BaseModel):
    analyzed: int
    cancelled: int
    simulated_success: int
    simulated_failure: int
    risk_levels: dict[str, int]        # {"low": 4, "medium": 2, "high": 1}
    top_reason_codes: list[dict]      # [{code, count}]
    recent: list[TransactionOut]


TokenResponse.model_rebuild()
TransactionDetailOut.model_rebuild()
AssessmentEmbed.model_rebuild()
