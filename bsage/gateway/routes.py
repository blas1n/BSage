"""HTTP route handlers for the BSage Gateway."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from bsage.gateway.dependencies import AppState

logger = structlog.get_logger(__name__)


class ConfigUpdate(BaseModel):
    """Request body for PATCH /api/config.

    Only fields included in the request body are changed.
    Use model_fields_set to distinguish 'not provided' from 'set to null'.
    """

    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    safe_mode: bool | None = None


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

    @api_router.get("/config")
    async def get_config() -> dict[str, Any]:
        """Return current runtime config (api_key excluded)."""
        return state.runtime_config.snapshot()

    @api_router.patch("/config")
    async def update_config(update: ConfigUpdate) -> dict[str, Any]:
        """Update runtime config. Only provided fields are changed."""
        provided = update.model_fields_set
        try:
            llm_kwargs: dict[str, Any] = {}
            if "llm_model" in provided:
                llm_kwargs["model"] = update.llm_model
            if "llm_api_key" in provided:
                llm_kwargs["api_key"] = update.llm_api_key
            if "llm_api_base" in provided:
                llm_kwargs["api_base"] = update.llm_api_base
            if llm_kwargs:
                state.runtime_config.update_llm(**llm_kwargs)
            if "safe_mode" in provided and update.safe_mode is not None:
                state.runtime_config.update_safe_mode(update.safe_mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return state.runtime_config.snapshot()

    return api_router
