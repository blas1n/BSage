"""FastAPI application factory for the BSage Gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from bsvibe_authz import get_settings_dep as _authz_get_settings_dep
from bsvibe_fastapi import RequestIdMiddleware, add_cors_middleware
from bsvibe_fastapi.settings import FastApiSettings
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from bsage.core.config import Settings
from bsage.gateway.authz import get_authz_settings
from bsage.gateway.dependencies import AppState
from bsage.gateway.mcp import create_mcp_routes
from bsage.gateway.mcp_api_keys_routes import create_mcp_api_keys_routes
from bsage.gateway.rate_limit import RateLimiter, RateLimitMiddleware
from bsage.gateway.routes import create_routes
from bsage.gateway.ws import create_ws_routes
from bsage.mcp.sse import create_sse_routes

logger = structlog.get_logger(__name__)

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Application settings. If None, loads from environment.

    Returns:
        Configured FastAPI application with all routes and lifecycle hooks.
    """
    if settings is None:
        from bsage.core.config import get_settings

        settings = get_settings()

    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await state.initialize()
        yield
        await state.shutdown()

    app = FastAPI(
        title="BSage Gateway",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.bsage = state

    # Phase 0 P0.5 — point bsvibe_authz at our tolerant settings adapter so
    # require_bsage_permission() can resolve when the deployment hasn't yet
    # bootstrapped OpenFGA (empty OPENFGA_API_URL → permissive mode).
    app.dependency_overrides[_authz_get_settings_dep] = get_authz_settings

    # Rate limiting — per-IP sliding window
    rate_limiter = RateLimiter(requests_per_minute=settings.rate_limit_per_minute)
    app.add_middleware(RateLimitMiddleware, rate_limiter=rate_limiter)

    # Phase A — request id correlation + structlog contextvars binding via
    # bsvibe-fastapi shared middleware.
    app.add_middleware(RequestIdMiddleware)

    # Phase A — CORS via bsvibe-fastapi shared helper. BSage keeps its
    # historical permissive policy (``allow_methods=["*"]`` / ``allow_headers=["*"]``)
    # by passing explicit overrides; the helper otherwise enforces the
    # BSVibe baseline ``Authorization`` / ``Content-Type`` allowlist.
    add_cors_middleware(
        app,
        FastApiSettings(),
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # Register API + MCP + WebSocket routes
    app.include_router(create_routes(state))
    app.include_router(create_mcp_routes(state))
    app.include_router(create_mcp_api_keys_routes(state))
    app.include_router(create_sse_routes(state))
    app.include_router(
        create_ws_routes(
            approval_interface=state.ws_approval_interface,
            auth_provider=state.auth_provider,
        )
    )

    # Serve built frontend (production)
    if _FRONTEND_DIST.is_dir():
        assets_dir = _FRONTEND_DIST / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="static")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> FileResponse:
            """SPA catch-all — serves index.html for all non-API routes."""
            return FileResponse(_FRONTEND_DIST / "index.html")

    return app
