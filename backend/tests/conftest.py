"""Test harness: fresh SQLite per test session + client + demo auth token."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEMP_DIR = tempfile.mkdtemp(prefix="secureupi-tests-")
os.environ["SECUREUPI_DATABASE_URL"] = f"sqlite:///{Path(TEMP_DIR) / 'test.db'}"
os.environ["SECUREUPI_SEED_DEMO_USERS"] = "0"
# deterministic 32+ byte dev secret for tests (satisfies RFC 7518 min length)
os.environ["SECUREUPI_JWT_SECRET"] = "test-secret-0123456789abcdef0123456789abcdef"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.base import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Transaction, User  # noqa: E402


@pytest.fixture(scope="session")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


DEMO_EMAIL = "itest@secureupi.app"
DEMO_PASSWORD = "itest-password-1"


@pytest.fixture(scope="session")
def token(client) -> str:
    # register once for the whole session
    r = client.post("/api/v1/auth/register", json={
        "name": "Integration Test", "email": DEMO_EMAIL,
        "password": DEMO_PASSWORD,
    })
    if r.status_code == 201:
        return r.json()["access_token"]
    # second call for a repeat session — log in instead
    r = client.post("/api/v1/auth/login", json={
        "name": "x", "email": DEMO_EMAIL, "password": DEMO_PASSWORD,
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture()
def auth_header(token):
    return {"Authorization": f"Bearer {token}"}
