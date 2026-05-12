"""FastAPI application factory for the BSage Gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from bsvibe_authz import get_settings_dep as _authz_get_settings_dep
from bsvibe_fastapi import RequestIdMiddleware, add_cors_middleware
from bsvibe_fastapi.settings import FastApiSettings
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from bsage.core.config import Settings
from bsage.gateway.authz import get_authz_settings
from bsage.gateway.dependencies import AppState
from bsage.gateway.mcp import create_mcp_routes
from bsage.gateway.rate_limit import RateLimiter, RateLimitMiddleware
from bsage.gateway.routes import create_routes
from bsage.gateway.ws import create_ws_routes
from bsage.mcp.oauth_protected_resource import (
    build_protected_resource_metadata,
    wrap_mcp_with_oauth_401,
)
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
    app.include_router(create_sse_routes(state))

    # RFC 9728 protected-resource discovery — MCP clients (Claude Code,
    # IDE plugins) bootstrap OAuth by hitting /mcp/* with no Authorization
    # header, getting back a 401 + WWW-Authenticate referencing this URL,
    # then discovering the authorization server from this body.
    @app.get("/.well-known/oauth-protected-resource", tags=["mcp"])
    async def oauth_protected_resource(request: Request) -> JSONResponse:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        resource_url = f"{proto}://{host}" if host else str(request.base_url).rstrip("/")
        return JSONResponse(
            content=build_protected_resource_metadata(
                resource_url=resource_url,
                authorization_server=settings.bsvibe_auth_url.rstrip("/"),
                scopes_supported=["sage:*"],
            ),
            headers={"Cache-Control": "public, max-age=300"},
        )

    # Wrap the MCP transport surface (`/mcp/sse`, `/mcp/messages/*`) so
    # unauthenticated requests return a 401 + WWW-Authenticate Bearer
    # challenge pointing at the metadata URL above. `/mcp/health` stays
    # unauthenticated (deploy probe). The /api/mcp/* REST router is on
    # a different prefix and unaffected.
    class _McpOAuthDiscoveryMiddleware:
        def __init__(self, inner_app: ASGIApp) -> None:
            self._inner = inner_app
            self._guarded = wrap_mcp_with_oauth_401(inner_app)

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope.get("type") != "http":
                await self._inner(scope, receive, send)
                return
            path = scope.get("path") or ""
            # Only guard the MCP transport endpoints — leave /mcp/health
            # and everything else (REST, frontend, /api/*) alone.
            if path == "/mcp/sse" or path.startswith("/mcp/messages"):
                await self._guarded(scope, receive, send)
                return
            await self._inner(scope, receive, send)

    app.add_middleware(_McpOAuthDiscoveryMiddleware)

    # Demo mode (separate deployment, BSVIBE_DEMO_MODE=true)
    from bsvibe_demo import is_demo_mode

    if is_demo_mode():
        from bsage.demo.router import demo_router
        from bsage.demo.seed import seed_demo_vault

        app.include_router(demo_router)
        # Pre-populate the shared demo vault with realistic notes so the
        # visitor's vault tree, search, and graph aren't empty. Idempotent
        # via a sentinel file; safe across container restarts.
        seed_demo_vault(state.vault.root)
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
