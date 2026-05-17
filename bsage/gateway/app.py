"""FastAPI application factory for the BSage Gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from bsvibe_fastapi import RequestIdMiddleware, add_cors_middleware
from bsvibe_fastapi.settings import FastApiSettings
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from bsage.core.config import Settings
from bsage.gateway.dependencies import AppState
from bsage.gateway.mcp import create_mcp_routes
from bsage.gateway.rate_limit import RateLimiter, RateLimitMiddleware
from bsage.gateway.routes import create_routes
from bsage.gateway.ws import create_ws_routes
from bsage.mcp.oauth_protected_resource import (
    build_protected_resource_metadata,
    wrap_mcp_with_oauth_401,
)
from bsage.mcp.streamable_http import build_streamable_http_app

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
        # Streamable HTTP MCP transport — the SDK's session manager owns a
        # task group that must be live before the first /mcp request. The
        # ASGI shim (mounted below) forwards requests into it; the manager
        # is built here so the lifespan owns its run() context.
        mcp_manager, mcp_asgi = build_streamable_http_app(state)
        app.state.mcp_asgi_app = mcp_asgi
        async with mcp_manager.run():
            logger.info("mcp_streamable_transport_started")
            yield
        app.state.mcp_asgi_app = None
        await state.shutdown()

    app = FastAPI(
        title="BSage Gateway",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.bsage = state

    # bsvibe-authz 1.2.0 — library ``Settings`` now defaults openfga_*/
    # bsvibe_auth_url/service_token_signing_secret to ``""``, so it
    # constructs fine on a partially-configured deployment. The previous
    # tolerant ``get_settings_dep`` override (with the deleted
    # ``gateway/authz.py`` adapter) is no longer needed — the standard
    # ``bsvibe_authz.get_settings_dep`` and the introspection client/cache
    # deps resolve directly from the library Settings.

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
                scopes_supported=["bsage:*"],
            ),
            headers={"Cache-Control": "public, max-age=300"},
        )

    # MCP server liveness — unauthenticated deploy probe. Declared as an
    # explicit route so it resolves BEFORE the /mcp Streamable HTTP mount
    # (a Mount swallows everything under its prefix). The /api/mcp/* REST
    # router is on a different prefix and unaffected.
    @app.get("/mcp/health", tags=["mcp"])
    async def mcp_health() -> JSONResponse:
        """MCP transport liveness + tool count — unauthenticated by design.

        Deploy probes (Claude Code bridges, k8s readiness) run before the
        auth backend is reachable. Reports the same registry the
        Streamable HTTP transport serves so the count is honest.
        """
        from bsage.mcp import plugin_bridge
        from bsage.mcp.server import build_registry

        registry = build_registry(state)
        plugin_tools = await plugin_bridge.list_plugins_as_tools(state)
        return JSONResponse(
            content={
                "status": "ok",
                "server": "bsage",
                "tool_count": len(list(registry.list_tools())) + len(plugin_tools),
            }
        )

    # Streamable HTTP MCP transport — mounted at /mcp. The lifespan owns
    # the session manager's run() context; this ASGI shim only forwards
    # requests into the manager stashed on app.state. Guarded by
    # wrap_mcp_with_oauth_401 so an unauthenticated request returns a
    # 401 + WWW-Authenticate Bearer challenge (RFC 9728) pointing at the
    # /.well-known/oauth-protected-resource metadata above — exactly the
    # posture the other three BSVibe products serve.
    async def _mcp_transport(scope: Scope, receive: Receive, send: Send) -> None:
        asgi = getattr(app.state, "mcp_asgi_app", None)
        if asgi is None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"error":"mcp_unavailable"}'})
            return
        await asgi(scope, receive, send)

    _mcp_transport_with_401 = wrap_mcp_with_oauth_401(_mcp_transport)
    app.router.routes.append(Mount("/mcp", app=_mcp_transport_with_401))

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
