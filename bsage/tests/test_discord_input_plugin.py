"""Tests for the discord-input plugin."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_context(vault_root: Path | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.credentials = {"bot_token": "dsc_token_123", "channel_id": "123456789"}
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    ctx.garden.resolve_plugin_state_path = MagicMock(
        side_effect=lambda plugin_name, subpath="_state.json": (vault_root or Path("/tmp")) / "seeds" / plugin_name / subpath
    )
    ctx.chat = None
    ctx.logger = MagicMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return execute function."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("discord_input", "plugins/discord-input/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


@pytest.mark.asyncio
async def test_execute_loads_successfully() -> None:
    """Test that execute function is importable and callable."""
    execute_fn = _load_plugin()

    assert callable(execute_fn)


@pytest.mark.asyncio
async def test_execute_returns_dict() -> None:
    """Test that execute returns a dict result."""
    execute_fn = _load_plugin()
    ctx = _make_context()

    result = await execute_fn(ctx)

    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_execute_has_collected_key() -> None:
    """Test that execute result has 'collected' key."""
    execute_fn = _load_plugin()
    ctx = _make_context()

    result = await execute_fn(ctx)

    assert "collected" in result
