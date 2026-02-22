"""FastAPI application factory for the BSage Gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from bsage.core.config import Settings
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes
from bsage.gateway.ws import create_ws_routes

logger = structlog.get_logger(__name__)


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

    # Register routes
    app.include_router(create_routes(state))
    app.include_router(create_ws_routes())

    return app
