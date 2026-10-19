"""Minimal in-memory sliding-window rate limiter (plan §11: API protection).

Good enough for the MVP / single-instance deploys; swap for Redis-based
limiting when moving to PostgreSQL + multiple instances.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = 60.0
        limit = settings.rate_limit_per_minute
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return JSONResponse({"error": "rate limit exceeded"},
                                    status_code=429)
            q.append(now)
        return await call_next(request)
