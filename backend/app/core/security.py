"""Security primitives: password hashing (PBKDF2) and HS256 JWT access tokens.

Sprint-1 scope: no third-party hashing dependency. PBKDF2-HMAC-SHA256 with a
per-user random salt meets the plan's "secure password hashing" requirement for
a demo without native deps. Tokens are signed with the configured secret,
carry the user id, and expire — auth must not outlive the demo session.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid

import jwt

from app.core.config import settings

_ITERATIONS = 390_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _ITERATIONS
    )
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iters)
        )
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, AttributeError):
        return False


def create_access_token(user_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + settings.jwt_ttl_minutes * 60,
        "jti": uuid.uuid4().hex,
        "iss": settings.app_name,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> str:
    """Returns the user id, or raises jwt.InvalidTokenError / ExpiredSignatureError."""
    data = jwt.decode(
        token, settings.jwt_secret, algorithms=["HS256"], issuer=settings.app_name
    )
    sub = data.get("sub")
    if not sub:
        raise jwt.InvalidTokenError("token missing subject")
    return sub
