"""HTTP route handlers for the BSage Gateway."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException

from bsage.gateway.dependencies import AppState

logger = structlog.get_logger(__name__)


def create_routes(state: AppState) -> APIRouter:
    """Create API routes with injected application state."""
    api_router = APIRouter(prefix="/api")

    @api_router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api_router.get("/skills")
    async def list_skills() -> list[dict[str, Any]]:
        registry = await state.skill_loader.load_all()
        return [
            {
                "name": meta.name,
                "version": meta.version,
                "category": meta.category,
                "is_dangerous": meta.is_dangerous,
                "description": meta.description,
            }
            for meta in registry.values()
        ]

    @api_router.post("/skills/{name}/run")
    async def run_skill(name: str) -> dict[str, Any]:
        try:
            state.skill_loader.get(name)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        try:
            results = await state.agent_loop.on_input(name, {})
            return {"skill": name, "results": results}
        except Exception as exc:
            logger.exception("skill_run_failed", skill=name)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @api_router.get("/vault/actions")
    async def list_actions() -> list[str]:
        notes = state.vault.read_notes("actions")
        return [str(p.name) for p in notes]

    return api_router
