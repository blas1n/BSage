"""Real MCP protocol server (stdio + SSE).

Builds a transport-agnostic ``mcp.server.Server`` instance with two
tool surfaces:

1. **Static read tools** from :mod:`bsage.gateway.mcp_tools`
   (``search_knowledge``, ``get_note``, ``get_graph_context``,
   ``list_recent``, ``create_note``).
2. **Dynamic plugin tools** registered through
   :mod:`bsage.mcp.plugin_bridge` — every plugin with
   ``mcp_exposed=True`` shows up automatically.

The actual transports (stdio for Claude Desktop, SSE for remote
clients) are mounted in :mod:`bsage.mcp.stdio` and
:mod:`bsage.gateway.app` respectively.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from mcp.server import Server
from mcp.types import TextContent, Tool

from bsage.garden.canonicalization import mcp_tools as canon_mcp_tools
from bsage.gateway import mcp_tools
from bsage.mcp import plugin_bridge

logger = structlog.get_logger(__name__)

SERVER_NAME = "bsage"


_STATIC_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "search_knowledge",
        "description": "Semantic search across BSage vault notes. Falls back to full-text search.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_note",
        "description": "Read a vault file by relative path (e.g. garden/seedling/foo.md).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Vault-relative file path"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_graph_context",
        "description": "Knowledge-graph BFS context for a topic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "max_hops": {"type": "integer", "default": 2, "minimum": 1, "maximum": 5},
                "top_k": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "list_recent",
        "description": (
            "Vault catalog grouped by maturity (seedling/budding/evergreen). "
            "For 'show me all my X' partition queries, prefer list_by_tag."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
    },
    {
        "name": "list_by_tag",
        "description": (
            "Notes carrying one or more of the given tags. Use for partition "
            "queries like 'all my project notes' (tags: ['project']). "
            "match='all' for AND, 'any' (default) for OR."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}},
                "match": {"type": "string", "enum": ["any", "all"], "default": "any"},
                "top_k": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
            },
            "required": ["tags"],
        },
    },
    {
        "name": "list_tags",
        "description": (
            "All tags in the vault sorted by frequency. Splits into a "
            "primary list (count >= threshold) and a long_tail list so "
            "the dominant topic vocabulary stays legible."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "threshold": {"type": "integer", "default": 3, "minimum": 1},
            },
        },
    },
    {
        "name": "browse_communities",
        "description": (
            "Louvain communities of the vault graph — emergent topic "
            "clusters with auto-generated labels. Navigate by 'topic "
            "neighbourhood' instead of by folder."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_size": {"type": "integer", "default": 2, "minimum": 1},
            },
        },
    },
    {
        "name": "browse_entity",
        "description": (
            "Backlinks + outgoing links + auto-stub flag for a single "
            "[[Name]] entity. Used to follow a wikilink and see the "
            "graph neighbourhood of a person/tool/concept/project."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Bare entity name (no [[ ]] brackets).",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_note",
        "description": (
            "Submit a note for ingestion — writes a seed and lets BSage's "
            "IngestCompiler classify and link it against existing vault content. "
            "The compiler decides note_type/tags/links; client-supplied tags and "
            "links are passed through as hints only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "source": {"type": "string", "default": "mcp"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "links": {"type": "array", "items": {"type": "string"}},
                "metadata": {"type": "object", "additionalProperties": True},
            },
            "required": ["title"],
        },
    },
]


_STATIC_DISPATCH = {
    "search_knowledge": mcp_tools.search_knowledge,
    "get_note": mcp_tools.get_note,
    "get_graph_context": mcp_tools.get_graph_context,
    "list_recent": mcp_tools.list_recent,
    "list_by_tag": mcp_tools.list_by_tag,
    "list_tags": mcp_tools.list_tags,
    "browse_communities": mcp_tools.browse_communities,
    "browse_entity": mcp_tools.browse_entity,
    "create_note": mcp_tools.create_note,
    **canon_mcp_tools.CANON_DISPATCH,
}


def build_server(state: Any) -> Server:
    """Construct an MCP Server with all tools registered against ``state``."""
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        tools = [_dict_to_tool(t) for t in _STATIC_TOOL_DEFS]
        # Canonicalization read tools (always exposed)
        tools.extend(_dict_to_tool(t) for t in canon_mcp_tools.CANON_TOOL_DEFS)
        if _canon_mutation_enabled(state):
            tools.extend(_dict_to_tool(t) for t in canon_mcp_tools.CANON_OPTIONAL_TOOL_DEFS)
        plugin_tools = await plugin_bridge.list_plugins_as_tools(state)
        tools.extend(_dict_to_tool(t) for t in plugin_tools)
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        result = await _dispatch_tool(state, name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    return server


def _canon_mutation_enabled(state: Any) -> bool:
    """Per Handoff §15.2 — MCP approval/mutation tools are off by default.

    Operators opt in by setting ``settings.mcp_canon_mutation_enabled``.
    """
    settings = getattr(state, "settings", None)
    return bool(getattr(settings, "mcp_canon_mutation_enabled", False))


async def _dispatch_tool(state: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Route a tool name to either the static handler or the plugin bridge."""
    static = _STATIC_DISPATCH.get(name)
    if static is not None:
        return await static(state, arguments)
    if _canon_mutation_enabled(state):
        optional = canon_mcp_tools.CANON_OPTIONAL_DISPATCH.get(name)
        if optional is not None:
            return await optional(state, arguments)
    return await plugin_bridge.invoke_plugin_as_tool(state, name, arguments)


def _dict_to_tool(d: dict[str, Any]) -> Tool:
    """Convert our internal {name, description, inputSchema} dict into mcp.Tool."""
    return Tool(
        name=d["name"],
        description=d.get("description", ""),
        inputSchema=d.get("inputSchema", {"type": "object"}),
    )
