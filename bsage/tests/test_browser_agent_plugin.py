"""Tests for the browser-agent plugin."""

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_context() -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = {
        "url": "https://example.com",
        "task": "extract page title",
    }
    ctx.credentials = {}
    ctx.garden = AsyncMock()
    ctx.garden.write_action = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    ctx.logger = MagicMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "browser_agent", "plugins/browser-agent/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


@pytest.mark.asyncio
async def test_execute_missing_url() -> None:
    """Test that execute returns error when url is missing."""
    execute_fn = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"task": "extract"}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "url" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_execute_missing_task() -> None:
    """Test that execute returns error when task is missing."""
    execute_fn = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"url": "https://example.com"}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "task" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_execute_empty_input() -> None:
    """Test that execute returns error when input is empty."""
    execute_fn = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "error" in result
