"""Model card endpoint — versioned model transparency (plan §11)."""
from __future__ import annotations

from fastapi import APIRouter

from app.ml import inference

router = APIRouter(tags=["model"])


@router.get("/model")
def model_card() -> dict:
    return inference.model_card()
