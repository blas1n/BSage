"""MCP (Model Context Protocol) endpoints for the BSage Gateway.

Provides tool-oriented endpoints that external AI agents (Claude, etc.)
can use to interact with BSage's knowledge base and skill system.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from bsage.core.plugin_loader import PluginMeta
from bsage.core.skill_loader import SkillMeta
from bsage.gateway import mcp_tools
from bsage.gateway.dependencies import AppState
from bsage.gateway.mcp_tools import _extract_body_preview as _extract_body_preview  # re-export

logger = structlog.get_logger(__name__)


# -- Request/Response models --------------------------------------------------


class SearchKnowledgeRequest(BaseModel):
    """Request body for search_knowledge tool."""

    query: str = Field(..., min_length=1, description="Semantic search query")
    top_k: int = Field(default=10, ge=1, le=50, description="Max results")


class SearchResult(BaseModel):
    """A single search result from knowledge search."""

    title: str
    path: str
    preview: str
    score: float
    tags: list[str]


class SearchKnowledgeResponse(BaseModel):
    """Response for search_knowledge tool."""

    results: list[SearchResult]
    query: str


class GraphContextRequest(BaseModel):
    """Request body for get_graph_context tool."""

    topic: str = Field(..., min_length=1, description="Topic to explore")
    max_hops: int = Field(default=2, ge=1, le=5, description="Graph traversal depth")
    top_k: int = Field(default=10, ge=1, le=50, description="Max related notes")


class GraphContextResponse(BaseModel):
    """Response for get_graph_context tool."""

    topic: str
    context: str
    has_results: bool


class RunSkillRequest(BaseModel):
    """Request body for run_skill tool."""

    skill_name: str = Field(..., min_length=1, description="Name of skill or plugin to run")
    params: dict[str, Any] = Field(default_factory=dict, description="Execution parameters")


class RunSkillResponse(BaseModel):
    """Response for run_skill tool."""

    skill_name: str
    results: Any
    success: bool


class PluginInfo(BaseModel):
    """Info about an installed plugin or skill."""

    name: str
    version: str
    category: str
    description: str
    kind: str  # "plugin" or "skill"
    enabled: bool
    has_credentials: bool
    credentials_configured: bool


class ListPluginsResponse(BaseModel):
    """Response for list_plugins tool."""

    entries: list[PluginInfo]
    total: int


# -- Router factory -----------------------------------------------------------


def create_mcp_routes(state: AppState) -> APIRouter:
    """Create MCP tool endpoints with injected application state.

    All MCP endpoints require authentication (protected).
    """
    router = APIRouter(
        prefix="/api/mcp",
        tags=["mcp"],
        dependencies=[Depends(state.get_current_user)],
    )

    @router.post("/search_knowledge", response_model=SearchKnowledgeResponse)
    async def search_knowledge(body: SearchKnowledgeRequest) -> SearchKnowledgeResponse:
        """Semantic search across the vault. Delegates to mcp_tools."""
        result = await mcp_tools.search_knowledge(state, body.model_dump())
        return SearchKnowledgeResponse(
            results=[SearchResult(**r) for r in result["results"]],
            query=result["query"],
        )

    @router.post("/get_graph_context", response_model=GraphContextResponse)
    async def get_graph_context(body: GraphContextRequest) -> GraphContextResponse:
        """Knowledge graph context for a topic. Delegates to mcp_tools."""
        if state.graph_retriever is None:
            raise HTTPException(status_code=503, detail="Knowledge graph not available")
        try:
            result = await mcp_tools.get_graph_context(state, body.model_dump())
        except Exception:
            logger.exception("mcp_graph_context_failed", topic=body.topic)
            raise HTTPException(
                status_code=500, detail="Internal error retrieving graph context"
            ) from None
        return GraphContextResponse(**result)

    @router.post("/run_skill", response_model=RunSkillResponse)
    async def run_skill(body: RunSkillRequest) -> RunSkillResponse:
        """Trigger execution of a skill or plugin by name.

        Delegates to the AgentLoop for proper context building and execution.
        """
        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        # Verify the entry exists
        try:
            state.agent_loop.get_entry(body.skill_name)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail="Skill not found in registry",
            ) from None

        # Check if disabled
        if body.skill_name in state.runtime_config.disabled_entries:
            raise HTTPException(status_code=403, detail="Skill is disabled")

        try:
            results = await state.agent_loop.on_input(body.skill_name, body.params)
            return RunSkillResponse(skill_name=body.skill_name, results=results, success=True)
        except Exception:
            logger.exception("mcp_run_skill_failed", skill=body.skill_name)
            return RunSkillResponse(
                skill_name=body.skill_name, results="Execution failed", success=False
            )

    @router.get("/list_plugins", response_model=ListPluginsResponse)
    async def list_plugins() -> ListPluginsResponse:
        """List all installed plugins and skills with their status."""
        entries: list[PluginInfo] = []
        configured_services = state.credential_store.list_services()
        disabled = state.runtime_config.disabled_entries

        # Plugins
        plugin_registry = await state.plugin_loader.load_all()
        for meta in plugin_registry.values():
            entries.append(_meta_to_plugin_info(meta, "plugin", configured_services, disabled))

        # Skills
        skill_registry = await state.skill_loader.load_all()
        for meta in skill_registry.values():
            entries.append(_meta_to_plugin_info(meta, "skill", configured_services, disabled))

        return ListPluginsResponse(entries=entries, total=len(entries))

    return router


# -- Helpers -------------------------------------------------------------------
# Note: ``_extract_body_preview`` lives in ``mcp_tools`` (re-exported above
# at module top so existing tests keep importing it from this module).


def _meta_to_plugin_info(
    meta: PluginMeta | SkillMeta,
    kind: str,
    configured_services: list[str],
    disabled: list[str],
) -> PluginInfo:
    """Convert a PluginMeta or SkillMeta to a PluginInfo response model."""
    creds = meta.credentials
    if isinstance(creds, list):
        has_credentials = bool(creds)
    elif isinstance(creds, dict):
        has_credentials = bool(creds.get("fields"))
    else:
        has_credentials = False

    credentials_configured = meta.name in configured_services if has_credentials else True

    enabled = False if has_credentials and not credentials_configured else meta.name not in disabled

    return PluginInfo(
        name=meta.name,
        version=meta.version,
        category=meta.category,
        description=meta.description,
        kind=kind,
        enabled=enabled,
        has_credentials=has_credentials,
        credentials_configured=credentials_configured,
    )
