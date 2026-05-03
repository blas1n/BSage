"""Tests for bsage.mcp.plugin_bridge — plugin metadata → MCP tool adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.mcp import plugin_bridge
from bsage.tests.conftest import make_plugin_meta


@pytest.fixture()
def state_with_plugins() -> MagicMock:
    """State mock with plugin_loader registry containing mixed mcp_exposed plugins."""
    state = MagicMock()

    exposed = make_plugin_meta(
        name="chatgpt-memory-input",
        category="input",
        description="Import ChatGPT export",
        input_schema={
            "type": "object",
            "properties": {"upload_id": {"type": "string"}},
            "required": ["upload_id"],
        },
        mcp_exposed=True,
    )
    hidden = make_plugin_meta(
        name="telegram-input",
        category="input",
        description="Telegram",
        mcp_exposed=False,
    )
    state.plugin_loader = MagicMock()
    state.plugin_loader.load_all = AsyncMock(
        return_value={
            "chatgpt-memory-input": exposed,
            "telegram-input": hidden,
        }
    )

    registry = {
        "chatgpt-memory-input": exposed,
        "telegram-input": hidden,
    }

    def _get_entry(name: str):
        if name not in registry:
            raise KeyError(name)
        return registry[name]

    state.agent_loop = MagicMock()
    state.agent_loop.get_entry = MagicMock(side_effect=_get_entry)
    state.agent_loop.on_input = AsyncMock(return_value=[{"status": "ok", "items": []}])

    state.runtime_config = MagicMock()
    state.runtime_config.disabled_entries = []
    return state


# -- list_plugins_as_tools ----------------------------------------------------


class TestListPluginsAsTools:
    @pytest.mark.asyncio
    async def test_only_returns_mcp_exposed_plugins(self, state_with_plugins: MagicMock) -> None:
        tools = await plugin_bridge.list_plugins_as_tools(state_with_plugins)
        names = {t["name"] for t in tools}
        assert "chatgpt-memory-input" in names
        assert "telegram-input" not in names

    @pytest.mark.asyncio
    async def test_tool_shape_matches_mcp_spec(self, state_with_plugins: MagicMock) -> None:
        tools = await plugin_bridge.list_plugins_as_tools(state_with_plugins)
        tool = next(t for t in tools if t["name"] == "chatgpt-memory-input")
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        # MCP requires JSON Schema object form
        assert tool["inputSchema"]["type"] == "object"
        assert "upload_id" in tool["inputSchema"]["properties"]

    @pytest.mark.asyncio
    async def test_uses_default_schema_when_input_schema_missing(self) -> None:
        state = MagicMock()
        meta = make_plugin_meta(name="x", mcp_exposed=True, input_schema=None)
        state.plugin_loader = MagicMock()
        state.plugin_loader.load_all = AsyncMock(return_value={"x": meta})
        state.runtime_config = MagicMock()
        state.runtime_config.disabled_entries = []

        tools = await plugin_bridge.list_plugins_as_tools(state)
        assert tools[0]["inputSchema"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_excludes_disabled_plugins(self, state_with_plugins: MagicMock) -> None:
        state_with_plugins.runtime_config.disabled_entries = ["chatgpt-memory-input"]
        tools = await plugin_bridge.list_plugins_as_tools(state_with_plugins)
        assert all(t["name"] != "chatgpt-memory-input" for t in tools)


# -- invoke_plugin_as_tool ----------------------------------------------------


class TestInvokePluginAsTool:
    @pytest.mark.asyncio
    async def test_calls_agent_loop_on_input(self, state_with_plugins: MagicMock) -> None:
        result = await plugin_bridge.invoke_plugin_as_tool(
            state_with_plugins,
            "chatgpt-memory-input",
            {"upload_id": "abc"},
        )
        state_with_plugins.agent_loop.on_input.assert_awaited_once_with(
            "chatgpt-memory-input", {"upload_id": "abc"}
        )
        assert result["success"] is True
        assert result["plugin"] == "chatgpt-memory-input"

    @pytest.mark.asyncio
    async def test_rejects_non_exposed_plugin(self, state_with_plugins: MagicMock) -> None:
        with pytest.raises(PermissionError):
            await plugin_bridge.invoke_plugin_as_tool(
                state_with_plugins,
                "telegram-input",
                {},
            )

    @pytest.mark.asyncio
    async def test_404_when_plugin_unknown(self, state_with_plugins: MagicMock) -> None:
        state_with_plugins.agent_loop.get_entry = MagicMock(side_effect=KeyError("nope"))
        with pytest.raises(KeyError):
            await plugin_bridge.invoke_plugin_as_tool(
                state_with_plugins,
                "nonexistent",
                {},
            )

    @pytest.mark.asyncio
    async def test_disabled_plugin_blocked(self, state_with_plugins: MagicMock) -> None:
        state_with_plugins.runtime_config.disabled_entries = ["chatgpt-memory-input"]
        with pytest.raises(PermissionError):
            await plugin_bridge.invoke_plugin_as_tool(
                state_with_plugins,
                "chatgpt-memory-input",
                {},
            )

    @pytest.mark.asyncio
    async def test_execution_error_returns_failure_dict(
        self, state_with_plugins: MagicMock
    ) -> None:
        state_with_plugins.agent_loop.on_input = AsyncMock(side_effect=RuntimeError("plugin crash"))
        result = await plugin_bridge.invoke_plugin_as_tool(
            state_with_plugins,
            "chatgpt-memory-input",
            {},
        )
        assert result["success"] is False
        assert "error" in result
