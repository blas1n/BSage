"""Tests for the browser-agent plugin."""

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_context() -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = {
        "action": "navigate",
        "url": "https://example.com",
    }
    ctx.credentials = {}
    ctx.garden = AsyncMock()
    ctx.garden.write_action = AsyncMock()
    ctx.logger = MagicMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return execute function."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("browser_agent", "plugins/browser-agent/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


@pytest.mark.asyncio
async def test_execute_requires_action() -> None:
    """Test that execute validates required action field."""
    execute_fn = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {}  # Missing action

    result = await execute_fn(ctx)

    assert result.get("success") is False
    assert "error" in result or "action" in str(result).lower()


@pytest.mark.asyncio
async def test_execute_returns_result_dict() -> None:
    """Test that execute returns a result dictionary."""
    execute_fn = _load_plugin()
    ctx = _make_context()

    result = await execute_fn(ctx)

    assert isinstance(result, dict)
    assert "success" in result or "error" in result
