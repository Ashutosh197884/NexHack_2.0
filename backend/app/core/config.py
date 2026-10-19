"""Runtime configuration, driven by environment variables (no secrets in code)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    app_name: str = "SecureUPI"
    api_prefix: str = "/api/v1"
    environment: str = os.environ.get("SECUREUPI_ENV", "development")
    # JWT: secret must come from the environment in any real deployment.
    jwt_secret: str = os.environ.get("SECUREUPI_JWT_SECRET", "")
    jwt_ttl_minutes: int = int(os.environ.get("SECUREUPI_JWT_TTL_MINUTES", "240"))
    database_url: str = os.environ.get("SECUREUPI_DATABASE_URL", "")
    # CORS: default to local dev origins only; production supply explicitly.
    cors_origins: list[str] = None  # type: ignore[assignment]
    # Input limits (validation per plan §11)
    max_qr_payload_chars: int = 2048
    max_transactions_per_user: int = 2000
    # Demo seeds: created on first boot so the app is usable immediately.
    seed_demo_users: bool = _bool("SECUREUPI_SEED_DEMO_USERS", True)
    demo_password: str = os.environ.get("SECUREUPI_DEMO_PASSWORD", "secureupi-demo")
    # Rate limiting (simple in-memory tokens-per-minute per client)
    rate_limit_per_minute: int = 120

    def resolved_cors_origins(self) -> list[str]:
        if self.cors_origins:
            return self.cors_origins
        raw = os.environ.get("SECUREUPI_CORS_ORIGINS", "")
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        return [
            "http://127.0.0.1:5173", "http://localhost:5173",
            "http://127.0.0.1:8077", "http://localhost:8077",
        ]


settings = Settings()
# Never ship a repo-committed default for production; dev fallback is ephemeral.
if not settings.jwt_secret:
    settings.jwt_secret = os.environ.get(
        "SECUREUPI_JWT_SECRET_AUTO", "dev-only-" + secrets.token_hex(24)
    )
settings.cors_origins = settings.resolved_cors_origins()

if not settings.database_url:
    settings.database_url = f"sqlite:///{BACKEND_DIR / 'secureupi.db'}"
