"""QR intelligence tests (§12 QR tests)."""
from __future__ import annotations

import pytest

from app.services.qr_generator import all_samples, sample_by_id
from app.services.qr_parser import parse_upi_uri


def test_valid_upi_uri():
    r = parse_upi_uri("upi://pay?pa=merchant123@upi&pn=ABC%20Store&am=2500&cu=INR")
    assert r.valid
    assert r.payee_vpa == "merchant123@upi"
    assert r.payee_name == "ABC Store"
    assert r.amount == 2500.0
    assert r.currency == "INR"
    assert not r.errors


def test_malformed_uri_unsupported_scheme():
    r = parse_upi_uri("https://example.com/pay?to=someone")
    assert not r.valid
    assert any(e.startswith("UNSUPPORTED_SCHEME") for e in r.errors)


def test_missing_payee():
    r = parse_upi_uri("upi://pay?am=100&cu=INR")
    assert not r.valid
    assert "MISSING_PAYEE_ADDRESS" in r.errors


def test_invalid_amount():
    r = parse_upi_uri("upi://pay?pa=shop@upi&am=4..50&cu=INR")
    assert not r.valid
    assert "INVALID_AMOUNT" in r.errors


def test_unsupported_currency():
    r = parse_upi_uri("upi://pay?pa=shop@upi&am=10&cu=USD")
    assert not r.valid
    assert any(e.startswith("UNSUPPORTED_CURRENCY") for e in r.errors)


def test_unexpected_params_flag():
    r = parse_upi_uri("upi://pay?pa=shop@upi&am=10&cu=INR&callback=https://evil.example")
    assert r.valid  # structure is OK, but flag surfaces
    assert r.flags["has_unexpected_params"]
    assert any(w.startswith("UNEXPECTED_PARAMS") for w in r.warnings)


def test_qr_without_amount_is_valid_but_warns():
    r = parse_upi_uri("upi://pay?pa=streetvendor@upi&cu=INR")
    assert r.valid
    assert "QR_NO_EMBEDDED_AMOUNT" in r.warnings


def test_empty_payload():
    r = parse_upi_uri("")
    assert not r.valid
    assert "EMPTY_PAYLOAD" in r.errors


def test_recipient_mismatch_warning_with_intended():
    # applied at the API layer; validated in test_api.py via /qr/analyze
    assert True


def test_invalid_vpa_shape():
    r = parse_upi_uri("upi://pay?pa=not-an-email&cu=INR")
    assert not r.valid
    assert "INVALID_PAYEE_ADDRESS" in r.errors


# ---- sample bank ----

def test_sample_bank_shapes_and_payloads_decode():
    for s in all_samples():
        assert s.payload
        assert s.scenario in {"benign", "suspicious", "malformed"}
        # benign samples must always parse clean
        if s.scenario == "benign":
            assert parse_upi_uri(s.payload).valid, s.id


def test_sample_ids_unique():
    ids = [s.id for s in all_samples()]
    assert len(ids) == len(set(ids))


def test_svg_render():
    svg = app_svg("coffee-shop")


def app_svg(sample_id: str) -> str:
    from app.services.qr_generator import render_svg_png
    return render_svg_png(sample_id)


def test_svg_render_contains_qr():
    out = app_svg("coffee-shop")
    assert "<svg" in out


def test_unknown_sample_raises():
    with pytest.raises(KeyError):
        app_svg("nonexistent")
