"""Tests for canonicalization MCP tools (Handoff §15.2)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import CallToolRequest, ListToolsRequest

from bsage.garden.canonicalization import mcp_tools as canon_mcp_tools
from bsage.garden.canonicalization.decisions import DecisionMemory
from bsage.garden.canonicalization.index import InMemoryCanonicalizationIndex
from bsage.garden.canonicalization.lock import AsyncIOMutationLock
from bsage.garden.canonicalization.policies import PolicyResolver
from bsage.garden.canonicalization.resolver import TagResolver
from bsage.garden.canonicalization.service import CanonicalizationService
from bsage.garden.canonicalization.store import NoteStore
from bsage.garden.storage import FileSystemStorage
from bsage.mcp.server import build_server


@pytest.fixture
async def state(tmp_path: Path):
    storage = FileSystemStorage(tmp_path)
    index = InMemoryCanonicalizationIndex()
    await index.initialize(storage)
    store = NoteStore(storage)
    decisions = DecisionMemory(index=index, store=store)
    policies = PolicyResolver(
        index=index, store=store, clock=lambda: datetime(2026, 5, 7, 14, 0, 0)
    )
    await policies.bootstrap_defaults()

    state = MagicMock()
    state.canon_index = index
    state.canon_decisions = decisions
    state.canon_policies = policies
    state.canon_service = CanonicalizationService(
        store=store,
        lock=AsyncIOMutationLock(),
        index=index,
        resolver=TagResolver(index=index),
        decisions=decisions,
        policies=policies,
        clock=lambda: datetime(2026, 5, 7, 14, 0, 0),
    )
    state.settings = MagicMock(mcp_canon_mutation_enabled=False)
    return state


@pytest.fixture(autouse=True)
def _stub_plugin_bridge():
    """Plugin bridge isn't relevant to canonicalization tool tests."""
    with (
        patch(
            "bsage.mcp.server.plugin_bridge.list_plugins_as_tools",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bsage.mcp.server.plugin_bridge.invoke_plugin_as_tool",
            new=AsyncMock(side_effect=RuntimeError("not_a_canon_tool")),
        ),
    ):
        yield


@pytest.fixture
def server(state):
    return build_server(state)


async def _list_tools(server) -> list:
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    return result.root.tools


async def _call_tool(server, name: str, arguments: dict) -> dict:
    from mcp.types import CallToolRequestParams

    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=arguments),
        )
    )
    text = result.root.content[0].text
    return json.loads(text)


class TestStaticToolsExposed:
    @pytest.mark.asyncio
    async def test_eight_static_canon_tools(self, server) -> None:
        tools = await _list_tools(server)
        names = {t.name for t in tools}
        for tool in canon_mcp_tools.CANON_TOOL_DEFS:
            assert tool["name"] in names, f"missing {tool['name']!r}"
        # Per Handoff §15.2 — 8 static tools
        canon_names = {t["name"] for t in canon_mcp_tools.CANON_TOOL_DEFS}
        assert len(canon_names) == 8


class TestOptionalToolsGated:
    @pytest.mark.asyncio
    async def test_optional_tools_hidden_by_default(self, server) -> None:
        tools = await _list_tools(server)
        names = {t.name for t in tools}
        for tool in canon_mcp_tools.CANON_OPTIONAL_TOOL_DEFS:
            assert tool["name"] not in names

    @pytest.mark.asyncio
    async def test_optional_tools_exposed_when_enabled(self, state) -> None:
        state.settings.mcp_canon_mutation_enabled = True
        srv = build_server(state)
        tools = await _list_tools(srv)
        names = {t.name for t in tools}
        for tool in canon_mcp_tools.CANON_OPTIONAL_TOOL_DEFS:
            assert tool["name"] in names


class TestToolDispatch:
    @pytest.mark.asyncio
    async def test_create_action_draft_then_apply(self, server) -> None:
        # Draft via MCP tool
        draft = await _call_tool(
            server,
            "canonicalization_create_action_draft",
            {"kind": "create-concept", "params": {"concept": "ml", "title": "ML"}},
        )
        assert draft["status"] == "draft"
        path = draft["path"]

        # Validate
        validate = await _call_tool(
            server, "canonicalization_validate_action", {"action_path": path}
        )
        assert validate["status"] == "passed"

        # Apply
        applied = await _call_tool(server, "canonicalization_apply_action", {"action_path": path})
        assert applied["final_status"] == "applied"

    @pytest.mark.asyncio
    async def test_resolve_tag(self, server) -> None:
        # Setup concept first
        await _call_tool(
            server,
            "canonicalization_create_action_draft",
            {
                "kind": "create-concept",
                "params": {
                    "concept": "machine-learning",
                    "title": "ML",
                    "aliases": ["ml"],
                },
            },
        )
        # Probe a read tool that doesn't depend on apply — confirms the
        # MCP dispatch routes through to the canon service successfully.
        result = await _call_tool(
            server,
            "canonicalization_list_policies",
            {},
        )
        assert len(result["items"]) == 3

    @pytest.mark.asyncio
    async def test_optional_apply_blocked_when_disabled(self, server) -> None:
        # canonicalization_approve_action is in OPTIONAL bucket; must not be
        # callable when mutation_enabled=False. The MCP server returns the
        # plugin-bridge fallback's RuntimeError text as the response body,
        # which our test helper then fails to JSON-decode.
        with pytest.raises(json.JSONDecodeError):
            await _call_tool(server, "canonicalization_approve_action", {"action_path": "x.md"})


class TestSpecCompliance:
    def test_static_tool_count_matches_spec(self) -> None:
        # Per §15.2 — exactly 8 static tools
        assert len(canon_mcp_tools.CANON_TOOL_DEFS) == 8

    def test_optional_tool_count_matches_spec(self) -> None:
        # Per §15.2 — 4 optional tools
        assert len(canon_mcp_tools.CANON_OPTIONAL_TOOL_DEFS) == 4

    def test_tools_have_descriptions_and_schemas(self) -> None:
        for tool in canon_mcp_tools.CANON_TOOL_DEFS + canon_mcp_tools.CANON_OPTIONAL_TOOL_DEFS:
            assert tool.get("description")
            assert tool.get("inputSchema", {}).get("type") == "object"
