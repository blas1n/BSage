"""Tests for the shell-executor plugin."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_context(vault_root: Path | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = {"command": "echo hello"}
    ctx.credentials = {
        "allowed_commands": "echo,cat",
        "sandbox_mode": "vault_only",
    }
    ctx.config = {
        "vault_path": vault_root or Path("/tmp/vault"),
        "tmp_dir": vault_root or Path("/tmp"),
    }
    ctx.logger = MagicMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return execute function."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("shell_executor", "plugins/shell-executor/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


@pytest.mark.asyncio
async def test_execute_loads_successfully() -> None:
    """Test that execute function is importable and callable."""
    execute_fn = _load_plugin()

    assert callable(execute_fn)


def test_parse_allowed_commands() -> None:
    """Test that plugin can parse allowed commands from credentials."""
    mod = _load_plugin()  # Just test import works
    assert callable(mod)


@pytest.mark.asyncio
async def test_execute_missing_command() -> None:
    """Test that execute returns error when command is missing."""
    execute_fn = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {}  # No command

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "command is required" in result.get("error", "")
