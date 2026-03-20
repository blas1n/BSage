"""Tests for the shell-executor plugin."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_context(vault_root: Path | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = {"command": "echo hello"}
    ctx.credentials = {
        "allowed_commands": "echo,cat",
        "sandbox_mode": "vault_only",
    }
    # Plugin accesses config as attributes (context.config.vault_path)
    config = MagicMock()
    config.vault_path = vault_root or Path("/tmp/vault")
    config.tmp_dir = vault_root or Path("/tmp")
    ctx.config = config
    ctx.garden = AsyncMock()
    ctx.garden.write_action = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    ctx.logger = MagicMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return (execute, module)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "shell_executor", "plugins/shell-executor/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute, mod


@pytest.mark.asyncio
async def test_execute_loads_successfully() -> None:
    """Test that execute function is importable and callable."""
    execute_fn, _ = _load_plugin()
    assert callable(execute_fn)


def test_parse_allowed_commands() -> None:
    """Test _parse_allowed_commands parses comma-separated strings."""
    _, mod = _load_plugin()
    assert mod._parse_allowed_commands("echo,cat,grep") == ["echo", "cat", "grep"]
    assert mod._parse_allowed_commands("") == []
    assert mod._parse_allowed_commands(None) == []
    assert mod._parse_allowed_commands("  ls , pwd ") == ["ls", "pwd"]


def test_validate_command() -> None:
    """Test _validate_command whitelist checking."""
    _, mod = _load_plugin()
    assert mod._validate_command("echo hello", ["echo", "cat"]) is True
    assert mod._validate_command("rm -rf /", ["echo", "cat"]) is False
    assert mod._validate_command("echo test", []) is True  # empty = allow all


@pytest.mark.asyncio
async def test_execute_missing_command() -> None:
    """Test that execute returns error when command is missing."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "command is required" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_blocked_command() -> None:
    """Test that execute blocks commands not in whitelist."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"command": "rm -rf /"}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "not in allowed list" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_runs_allowed_command(tmp_path: Path) -> None:
    """Test that execute runs an allowed command and returns output."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    result = await execute_fn(ctx)

    assert result["success"] is True
    assert "hello" in result["stdout"]
    ctx.garden.write_action.assert_awaited_once()
    ctx.garden.write_seed.assert_awaited_once()
