"""QR endpoints — analyze + synthetic sample bank (§8.1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.db.base import get_db
from app.schemas.qr import QrAnalyzeRequest, QrAnalyzeResponse, QrSampleOut
from app.services import audit
from app.services.qr_generator import all_samples, render_svg_png, sample_by_id
from app.services.qr_parser import parse_upi_uri

router = APIRouter(prefix="/qr", tags=["qr"])


def _mismatch_warning(parsed_vpa: str | None, intended: str | None) -> list[str]:
    if not intended:
        return []
    if parsed_vpa and parsed_vpa.lower() != intended.lower().strip():
        return [f"RECIPIENT_MISMATCH:QR encodes {parsed_vpa}, you intended "
                f"{intended} — double-check before paying."]
    return []


@router.post("/analyze", response_model=QrAnalyzeResponse)
def analyze(body: QrAnalyzeRequest, db=Depends(get_db), user_id: str | None = None,
            request: Request = None) -> QrAnalyzeResponse:  # noqa: ANN001
    parsed = parse_upi_uri(body.qr_payload)
    warnings = list(parsed.warnings) + _mismatch_warning(
        parsed.payee_vpa, body.intended_recipient
    )

    # Sample-id echo lets the demo show which of the generated QRs was scanned.
    qrid = None
    for s in all_samples():
        if s.payload == body.qr_payload:
            qrid = s.id
            break

    if user_id is not None:
        audit.log(db, user_id=user_id, event_type="QR_ANALYZED", resource_id=qrid)

    return QrAnalyzeResponse(
        valid=parsed.valid,
        payment_data={
            "payee_vpa": parsed.payee_vpa,
            "payee_name": parsed.payee_name,
            "amount": parsed.amount,
            "currency": parsed.currency,
            "reference": parsed.reference,
            "note": parsed.note,
        },
        qrid=qrid,
        errors=list(parsed.errors),
        warnings=warnings,
        flags=parsed.flags,
    )


@router.get("/samples", response_model=list[QrSampleOut])
def samples() -> list[QrSampleOut]:
    return [QrSampleOut(**s.model_dump()) for s in all_samples()]


@router.get("/samples/{sample_id}/image.svg")
def sample_image(sample_id: str) -> Response:
    try:
        svg = render_svg_png(sample_id)
    except KeyError:
        raise HTTPException(404, detail={"error": "unknown sample"})
    return Response(content=svg, media_type="image/svg+xml")
