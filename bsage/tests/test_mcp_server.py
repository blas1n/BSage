"""Tests for bsage.mcp.server — MCP server tool registration + dispatch."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.mcp import server as mcp_server
from bsage.tests.conftest import make_plugin_meta


@pytest.fixture()
def state() -> MagicMock:
    s = MagicMock()
    s.vault = MagicMock()
    s.vault.root = Path("/vault")
    s.vault.resolve_path = MagicMock(side_effect=lambda p: Path(f"/vault/{p}"))
    s.vault.read_note_content = AsyncMock(return_value="# X\nbody")
    s.embedder = MagicMock()
    s.embedder.enabled = False
    s.vector_store = None
    s.retriever = MagicMock()
    s.retriever.search = AsyncMock(return_value="search-result")
    s.graph_retriever = MagicMock()
    s.graph_retriever.retrieve = AsyncMock(return_value="graph context")
    s.index_reader = MagicMock()
    s.index_reader.get_all_summaries = AsyncMock(return_value=[])
    s.garden_writer = MagicMock()
    s.garden_writer.write_garden = AsyncMock(return_value=Path("/vault/garden/idea/x.md"))
    s.runtime_config = MagicMock()
    s.runtime_config.disabled_entries = []

    exposed = make_plugin_meta(name="my-input", mcp_exposed=True, category="input")
    s.plugin_loader = MagicMock()
    s.plugin_loader.load_all = AsyncMock(return_value={"my-input": exposed})

    s.agent_loop = MagicMock()
    s.agent_loop.get_entry = MagicMock(return_value=exposed)
    s.agent_loop.on_input = AsyncMock(return_value=[{"status": "ok"}])
    return s


class TestStaticTools:
    def test_static_tool_count(self) -> None:
        # Step B5 added list_by_tag / list_tags / browse_communities /
        # browse_entity for the dynamic-ontology navigation surface.
        names = {t["name"] for t in mcp_server._STATIC_TOOL_DEFS}
        assert names == {
            "search_knowledge",
            "get_note",
            "get_graph_context",
            "list_recent",
            "list_by_tag",
            "list_tags",
            "browse_communities",
            "browse_entity",
            "create_note",
        }

    def test_static_tools_have_input_schema(self) -> None:
        for t in mcp_server._STATIC_TOOL_DEFS:
            assert t["inputSchema"]["type"] == "object"


class TestServerBuild:
    @pytest.mark.asyncio
    async def test_build_server_returns_server_with_handlers(self, state: MagicMock) -> None:
        server = mcp_server.build_server(state)
        # mcp.server.Server exposes ``request_handlers`` after decorators run
        assert server.name == mcp_server.SERVER_NAME
        # Decorators registered: list_tools + call_tool
        assert hasattr(server, "request_handlers")


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_static_tool(self, state: MagicMock) -> None:
        result = await mcp_server._dispatch_tool(state, "search_knowledge", {"query": "hi"})
        assert "results" in result

    @pytest.mark.asyncio
    async def test_dispatch_plugin_tool(self, state: MagicMock) -> None:
        result = await mcp_server._dispatch_tool(state, "my-input", {"upload_id": "x"})
        assert result["plugin"] == "my-input"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool_raises(self, state: MagicMock) -> None:
        state.agent_loop.get_entry = MagicMock(side_effect=KeyError("nope"))
        with pytest.raises(KeyError):
            await mcp_server._dispatch_tool(state, "totally-unknown", {})


class TestListToolsHandler:
    @pytest.mark.asyncio
    async def test_includes_static_and_dynamic(self, state: MagicMock) -> None:
        # Trigger _list_tools by calling the registered list_tools handler.
        # The server stores it in request_handlers under the appropriate
        # request type. Easier: invoke the inline closure via a direct call
        # by reaching into the server's bound handler.
        server = mcp_server.build_server(state)
        # Find the registered list_tools handler. mcp Server stores them
        # in `notification_handlers` / `request_handlers` keyed by type.
        from mcp.types import ListToolsRequest

        handler = server.request_handlers[ListToolsRequest]
        req = ListToolsRequest(method="tools/list", params=None)
        # Build a minimal context-less call. The mcp lowlevel handler
        # accepts the request object directly.
        result = await handler(req)
        # ServerResult wraps a ListToolsResult
        tools = result.root.tools
        names = {t.name for t in tools}
        assert "search_knowledge" in names
        assert "create_note" in names
        assert "my-input" in names


class TestCallToolHandler:
    @pytest.mark.asyncio
    async def test_call_tool_returns_text_content(self, state: MagicMock) -> None:
        server = mcp_server.build_server(state)
        from mcp.types import CallToolRequest, CallToolRequestParams

        handler = server.request_handlers[CallToolRequest]
        params = CallToolRequestParams(name="search_knowledge", arguments={"query": "hi"})
        req = CallToolRequest(method="tools/call", params=params)
        result = await handler(req)
        # ServerResult -> CallToolResult with content list
        content = result.root.content
        assert len(content) >= 1
        assert content[0].type == "text"
        # The text must be JSON we can parse (search result dict)
        payload = json.loads(content[0].text)
        assert "results" in payload
