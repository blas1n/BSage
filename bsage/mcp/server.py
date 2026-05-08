"""Real MCP protocol server (stdio + SSE).

Builds a transport-agnostic ``mcp.server.Server`` instance backed by the
first-class :class:`bsage.mcp.api.ToolRegistry` (Phase 7 / TASK-002).
Three tool surfaces share the registry:

1. **Domain static tools** — :mod:`bsage.mcp.domain_tools` registers the
   nine knowledge tools (``search_knowledge``, ``get_note``,
   ``get_graph_context``, ``list_recent``, ``list_by_tag``,
   ``list_tags``, ``browse_communities``, ``browse_entity``,
   ``create_note``).
2. **Canonicalization tools** — :mod:`bsage.garden.canonicalization
   .mcp_tools` registers the eight read tools always; the four mutation
   tools are gated by ``settings.mcp_canon_mutation_enabled``.
3. **Dynamic plugin tools** — :mod:`bsage.mcp.plugin_bridge` exposes any
   plugin with ``mcp_exposed=True`` directly through plugin loader
   (these stay outside the typed registry because plugins author their
   own JSON Schemas at decorator time).

Old ``_STATIC_TOOL_DEFS`` / ``_STATIC_DISPATCH`` constants are derived
from the registry so the legacy import surface used by existing tests
keeps working.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from mcp.server import Server
from mcp.types import TextContent, Tool

from bsage.garden.canonicalization import mcp_tools as canon_mcp_tools
from bsage.mcp import plugin_bridge
from bsage.mcp.api import ToolContext, ToolError, ToolRegistry
from bsage.mcp.domain_tools import register_domain_tools

logger = structlog.get_logger(__name__)

SERVER_NAME = "bsage"


# ---------------------------------------------------------------------------
# Legacy module surface — preserved so existing tests / introspection that
# imports ``_STATIC_TOOL_DEFS`` / ``_STATIC_DISPATCH`` keeps working. The
# actual MCP wire flow goes through the per-build ToolRegistry in
# ``build_server`` — these dicts are derived snapshots, not the source
# of truth.
# ---------------------------------------------------------------------------
def _domain_static_defs() -> list[dict[str, Any]]:
    snapshot_registry = ToolRegistry()
    register_domain_tools(snapshot_registry)
    return [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.inputSchema,
        }
        for t in snapshot_registry.list_tools()
    ]


_STATIC_TOOL_DEFS: list[dict[str, Any]] = _domain_static_defs()


# Legacy ``(state, args) -> dict`` adapters that route through the
# ToolRegistry — preserves the contract used by ``_dispatch_tool`` and
# any external callers that still imported the old ``_STATIC_DISPATCH``
# mapping.
def _legacy_static_dispatch() -> dict[str, Any]:
    snapshot = ToolRegistry()
    register_domain_tools(snapshot)
    canon_mcp_tools.register_canon_tools(snapshot, mutation_enabled=True)

    def _make(name: str) -> Any:
        async def _call(state: Any, args: dict[str, Any]) -> dict[str, Any]:
            return await snapshot.call_tool(name, args, ToolContext(state=state))

        return _call

    return {name: _make(name) for name in snapshot.names()}


_STATIC_DISPATCH: dict[str, Any] = _legacy_static_dispatch()


# ---------------------------------------------------------------------------
# build_server — primary entry. Constructs a fresh ToolRegistry per call
# (so canon mutation gating can flip per-state) and wires both the
# ``ListTools`` and ``CallTool`` MCP request handlers.
# ---------------------------------------------------------------------------
def build_server(state: Any) -> Server:
    """Construct an MCP Server with all tools registered against ``state``."""
    server: Server = Server(SERVER_NAME)
    registry = _build_registry(state)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        tools: list[Tool] = list(registry.list_tools())
        plugin_tools = await plugin_bridge.list_plugins_as_tools(state)
        tools.extend(_dict_to_tool(t) for t in plugin_tools)
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        result = await _dispatch_via_registry(state, registry, name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    return server


def _build_registry(state: Any) -> ToolRegistry:
    registry = ToolRegistry()
    register_domain_tools(registry)
    canon_mcp_tools.register_canon_tools(
        registry,
        mutation_enabled=_canon_mutation_enabled(state),
    )
    return registry


def _canon_mutation_enabled(state: Any) -> bool:
    """Per Handoff §15.2 — MCP approval/mutation tools are off by default.

    Operators opt in by setting ``settings.mcp_canon_mutation_enabled``.
    """
    settings = getattr(state, "settings", None)
    return bool(getattr(settings, "mcp_canon_mutation_enabled", False))


# ---------------------------------------------------------------------------
# Dispatch helpers — first-class registry, then plugin bridge fallback.
# ---------------------------------------------------------------------------
async def _dispatch_via_registry(
    state: Any,
    registry: ToolRegistry,
    name: str,
    arguments: dict[str, Any],
) -> Any:
    if name in registry:
        ctx = ToolContext(
            state=state,
            settings=getattr(state, "settings", None),
            audit_outbox=getattr(state, "audit_outbox", None),
        )
        try:
            return await registry.call_tool(name, arguments, ctx)
        except ToolError:
            # ToolError is wire-safe — surface its message verbatim so
            # the MCP framework's call_tool wrapper can render it as
            # error content.
            raise
    return await plugin_bridge.invoke_plugin_as_tool(state, name, arguments)


async def _dispatch_tool(state: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Legacy module-level dispatcher. Tests pin this signature.

    Builds a per-call registry (cheap — just dataclass construction) so
    the test contract (canon optional gated by
    ``settings.mcp_canon_mutation_enabled``, plugin fallback via
    ``plugin_bridge``) holds without mutating module state.
    """
    registry = _build_registry(state)
    return await _dispatch_via_registry(state, registry, name, arguments)


def _dict_to_tool(d: dict[str, Any]) -> Tool:
    """Convert plugin-bridge ``{name, description, inputSchema}`` dict into mcp.Tool."""
    return Tool(
        name=d["name"],
        description=d.get("description", ""),
        inputSchema=d.get("inputSchema", {"type": "object"}),
    )
