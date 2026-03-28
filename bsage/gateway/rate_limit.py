"""In-memory sliding-window rate limiter middleware for FastAPI."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = structlog.get_logger(__name__)


@dataclass
class _WindowState:
    """Sliding window state for a single client."""

    timestamps: list[float] = field(default_factory=list)


class RateLimiter:
    """Simple in-memory sliding-window rate limiter.

    Tracks request timestamps per client IP and rejects requests
    that exceed the configured limit within a 60-second window.
    """

    def __init__(self, requests_per_minute: int = 60) -> None:
        self._limit = requests_per_minute
        self._window_seconds = 60.0
        self._clients: dict[str, _WindowState] = defaultdict(_WindowState)

    @property
    def limit(self) -> int:
        """Current rate limit (requests per minute)."""
        return self._limit

    def is_allowed(self, client_ip: str) -> tuple[bool, int]:
        """Check if a request from the given IP is allowed.

        Returns:
            Tuple of (allowed, remaining_requests).
        """
        now = time.monotonic()
        state = self._clients[client_ip]

        # Remove timestamps outside the sliding window
        cutoff = now - self._window_seconds
        state.timestamps = [ts for ts in state.timestamps if ts > cutoff]

        if len(state.timestamps) >= self._limit:
            return False, 0

        state.timestamps.append(now)
        remaining = self._limit - len(state.timestamps)
        return True, remaining


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces per-IP rate limiting.

    Applies to all routes under /api/ except health checks.
    Returns HTTP 429 with Retry-After header when the limit is exceeded.
    """

    def __init__(self, app: Callable, rate_limiter: RateLimiter) -> None:
        super().__init__(app)
        self._limiter = rate_limiter

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check rate limit before processing the request."""
        path = request.url.path

        # Skip rate limiting for non-API routes and health checks
        if not path.startswith("/api/") or path == "/api/health":
            return await call_next(request)

        client_ip = _get_client_ip(request)
        allowed, remaining = self._limiter.is_allowed(client_ip)

        if not allowed:
            logger.warning("rate_limit_exceeded", client_ip=client_ip, path=path)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(self._limiter.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._limiter.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
