"""SecureUPI backend — FastAPI app (Sprint 1 vertical slice).

Run from backend/:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.base import SessionLocal, engine, init_db
from app.db.seed import seed_if_empty
from app.api.ratelimit import RateLimitMiddleware
from app.api.v1 import auth, dashboard, model as model_api, qr, risk, transactions


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # seed demo data (skipped in tests via settings.seed_demo_users=False)
    if settings.seed_demo_users:
        with SessionLocal() as db:
            seed_if_empty(db, enabled=settings.seed_demo_users,
                          demo_password=settings.demo_password)
    yield
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "AI-powered pre-authorization risk layer for UPI payments.\n\n"
        "Enable / disable the simulated QR scanner + risk engine "
        "(response examples in the docs)."
    ),
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

prefix = settings.api_prefix
app.include_router(auth.router, prefix=prefix)
app.include_router(qr.router, prefix=prefix)
app.include_router(risk.router, prefix=prefix)
app.include_router(transactions.router, prefix=prefix)
app.include_router(dashboard.router, prefix=prefix)
app.include_router(model_api.router, prefix=prefix)


@app.get(f"{prefix}/health", tags=["health"])
def health() -> dict:
    """Health probe (§8.1). Reports ML artifact availability honestly."""
    from app.ml import inference
    return {
        "ok": True,
        "service": "secureupi-backend",
        "environment": settings.environment,
        "ml_ok": inference.is_available(),
        "model_available": inference.is_available(),
    }
