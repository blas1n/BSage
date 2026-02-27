"""HTTP route handlers for the BSage Gateway."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from bsage.gateway.chat import handle_chat
from bsage.gateway.dependencies import AppState

logger = structlog.get_logger(__name__)


class ChatMessage(BaseModel):
    """Request body for POST /api/chat."""

    message: str
    history: list[dict[str, Any]] = []
    context_paths: list[str] | None = None


class ConfigUpdate(BaseModel):
    """Request body for PATCH /api/config.

    Only fields included in the request body are changed.
    Use model_fields_set to distinguish 'not provided' from 'set to null'.
    """

    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    safe_mode: bool | None = None


def _meta_to_dict(meta: Any, danger_map: dict[str, bool] | None = None) -> dict[str, Any]:
    """Serialize a PluginMeta or SkillMeta to a JSON-safe dict."""
    return {
        "name": meta.name,
        "version": meta.version,
        "category": meta.category,
        "is_dangerous": (danger_map or {}).get(meta.name, False),
        "description": meta.description,
    }


def create_routes(state: AppState) -> APIRouter:
    """Create API routes with injected application state."""
    api_router = APIRouter(prefix="/api")

    @api_router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api_router.get("/plugins")
    async def list_plugins() -> list[dict[str, Any]]:
        """List all loaded Plugins (code-based)."""
        registry = await state.plugin_loader.load_all()
        return [_meta_to_dict(meta, state.danger_map) for meta in registry.values()]

    @api_router.get("/skills")
    async def list_skills() -> list[dict[str, Any]]:
        """List all loaded Skills (LLM-based)."""
        registry = await state.skill_loader.load_all()
        return [_meta_to_dict(meta, state.danger_map) for meta in registry.values()]

    @api_router.post("/plugins/{name}/run")
    async def run_plugin(name: str) -> dict[str, Any]:
        """Trigger a plugin by name via AgentLoop.on_input."""
        try:
            state.plugin_loader.get(name)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        try:
            results = await state.agent_loop.on_input(name, {})
            return {"plugin": name, "results": results}
        except Exception as exc:
            logger.exception("plugin_run_failed", plugin=name)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @api_router.post("/webhooks/{name}")
    async def webhook(name: str, request: Request) -> dict[str, Any]:
        """Receive a webhook payload and trigger an input plugin."""
        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        try:
            state.plugin_loader.get(name)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            body = await request.json()
        except Exception:
            body = {}

        try:
            results = await state.agent_loop.on_input(name, body)
            return {"plugin": name, "results": results}
        except Exception as exc:
            logger.exception("webhook_plugin_failed", plugin=name)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @api_router.post("/run/{name}")
    async def run_entry(name: str) -> dict[str, Any]:
        """Run a plugin or skill by name via unified registry.

        Unlike ``/plugins/{name}/run``, this endpoint checks both plugins
        and skills in the unified AgentLoop registry.
        """
        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        try:
            state.agent_loop.get_entry(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"'{name}' not found in registry") from None

        try:
            results = await state.agent_loop.on_input(name, {})
            return {"name": name, "results": results}
        except Exception as exc:
            logger.exception("run_entry_failed", name=name)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @api_router.get("/vault/actions")
    async def list_actions() -> list[str]:
        notes = await state.vault.read_notes("actions")
        return [str(p.name) for p in notes]

    @api_router.get("/config")
    async def get_config() -> dict[str, Any]:
        """Return current runtime config (api_key excluded)."""
        return state.runtime_config.snapshot()

    @api_router.patch("/config")
    async def update_config(update: ConfigUpdate) -> dict[str, Any]:
        """Update runtime config. Only provided fields are changed."""
        changes: dict[str, Any] = {
            field: getattr(update, field)
            for field in update.model_fields_set
            if field != "safe_mode" or update.safe_mode is not None
        }
        if not changes:
            return state.runtime_config.snapshot()
        try:
            state.runtime_config.update(**changes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return state.runtime_config.snapshot()

    @api_router.post("/chat")
    async def chat(body: ChatMessage) -> dict[str, str]:
        """Vault-aware conversational chat with plugin tool use."""
        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")
        try:
            response = await handle_chat(
                message=body.message,
                history=body.history,
                agent_loop=state.agent_loop,
                garden_writer=state.garden_writer,
                prompt_registry=state.prompt_registry,
                context_paths=body.context_paths,
                retriever=state.retriever,
            )
            return {"response": response}
        except Exception as exc:
            logger.exception("chat_failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @api_router.get("/sync-backends")
    async def list_sync_backends() -> list[str]:
        """Return names of registered sync backends."""
        return state.sync_manager.list_backends()

    return api_router
