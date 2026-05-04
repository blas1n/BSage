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
        "description": "Read a vault file by relative path (e.g. garden/idea/foo.md).",
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
        "description": "Vault catalog grouped by note type.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
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
    "create_note": mcp_tools.create_note,
}


def build_server(state: Any) -> Server:
    """Construct an MCP Server with all tools registered against ``state``."""
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        tools = [_dict_to_tool(t) for t in _STATIC_TOOL_DEFS]
        plugin_tools = await plugin_bridge.list_plugins_as_tools(state)
        tools.extend(_dict_to_tool(t) for t in plugin_tools)
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        result = await _dispatch_tool(state, name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    return server


async def _dispatch_tool(state: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Route a tool name to either the static handler or the plugin bridge."""
    static = _STATIC_DISPATCH.get(name)
    if static is not None:
        return await static(state, arguments)
    return await plugin_bridge.invoke_plugin_as_tool(state, name, arguments)


def _dict_to_tool(d: dict[str, Any]) -> Tool:
    """Convert our internal {name, description, inputSchema} dict into mcp.Tool."""
    return Tool(
        name=d["name"],
        description=d.get("description", ""),
        inputSchema=d.get("inputSchema", {"type": "object"}),
    )
