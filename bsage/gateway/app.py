"""FastAPI application factory for the BSage Gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from bsage.core.config import Settings
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes
from bsage.gateway.ws import create_ws_routes

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

    # CORS — allows Vite dev server (port 5173) during development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API + WebSocket routes
    app.include_router(create_routes(state))
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
