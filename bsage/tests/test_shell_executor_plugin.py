"""Tests for the shell-executor plugin."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bsage.tests.conftest import make_plugin_context

_DEFAULT_CREDS = {"allowed_commands": "echo,cat", "sandbox_mode": "vault_only"}


def _make_context(vault_root: Path | None = None) -> MagicMock:
    root = vault_root or Path("/nonexistent/vault")
    return make_plugin_context(
        input_data={"command": "echo hello"},
        credentials=_DEFAULT_CREDS,
        vault_root=vault_root,
        include_write_action=True,
        include_notify=True,
        config_overrides={
            "vault_path": root,
            "tmp_dir": vault_root or Path("/nonexistent"),
            "safe_mode": True,
        },
    )


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
    # Empty whitelist = unrestricted mode (allow ALL commands)
    assert mod._validate_command("echo test", []) is True
    assert mod._validate_command("rm -rf /", []) is True
    assert mod._validate_command("arbitrary_cmd --flag", []) is True


def test_validate_command_malformed_quotes() -> None:
    """Test _validate_command handles malformed shell quotes gracefully."""
    _, mod = _load_plugin()
    # Unbalanced quotes should not crash, should return False
    result = mod._validate_command("echo 'unterminated", ["echo"])
    assert result is False


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
    execute_fn, mod = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    mock_result = MagicMock(returncode=0, stdout="hello world\n", stderr="")
    with patch.object(mod, "subprocess") as mock_sp:
        mock_sp.run.return_value = mock_result
        mock_sp.TimeoutExpired = subprocess.TimeoutExpired
        result = await execute_fn(ctx)

    assert result["success"] is True
    assert "hello" in result["stdout"]
    ctx.garden.write_action.assert_awaited_once()
    ctx.garden.write_seed.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_system_mode_blocked_by_safe_mode() -> None:
    """Test that system sandbox_mode is blocked when safe_mode is True."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.credentials = {"sandbox_mode": "system", "allowed_commands": ""}
    ctx.config.safe_mode = True

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "SafeMode" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_system_mode_allowed_when_safe_mode_disabled(tmp_path: Path) -> None:
    """Test that system sandbox_mode works when safe_mode is disabled."""
    execute_fn, mod = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)
    ctx.credentials = {"sandbox_mode": "system", "allowed_commands": "echo"}
    ctx.config.safe_mode = False

    mock_result = MagicMock(returncode=0, stdout="hello world\n", stderr="")
    with patch.object(mod, "subprocess") as mock_sp:
        mock_sp.run.return_value = mock_result
        mock_sp.TimeoutExpired = subprocess.TimeoutExpired
        result = await execute_fn(ctx)

    assert result["success"] is True
    assert "hello" in result["stdout"]


@pytest.mark.asyncio
async def test_execute_invalid_timeout() -> None:
    """Test that execute rejects invalid timeout values."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"command": "echo hello", "timeout_s": "not_a_number"}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "timeout_s must be numeric" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_negative_timeout() -> None:
    """Test that execute rejects negative timeout values."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"command": "echo hello", "timeout_s": -5}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "timeout_s must be at least 1 second" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_path_outside_vault(tmp_path: Path) -> None:
    """Test that vault_only mode blocks paths outside vault."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)
    ctx.input_data = {"command": "echo hello", "working_dir": "/etc"}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "outside vault/tmp" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_symlink_escape_blocked(tmp_path: Path) -> None:
    """Test that symlink escaping the vault boundary is blocked."""
    execute_fn, _ = _load_plugin()

    # Create a symlink inside vault that points outside
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    escape_link = vault_dir / "escape"
    escape_link.symlink_to("/tmp")

    ctx = _make_context(vault_root=vault_dir)
    ctx.input_data = {"command": "echo hello", "working_dir": str(escape_link)}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "outside vault/tmp" in result.get("error", "")


def test_run_subprocess_malformed_command(tmp_path: Path) -> None:
    """Test _run_subprocess handles malformed command strings."""
    _, mod = _load_plugin()
    result = mod._run_subprocess("echo 'unterminated", str(tmp_path), 5.0)

    assert result["returncode"] == 1
    assert "Invalid command syntax" in result["stderr"]


@pytest.mark.asyncio
async def test_notify_sends_output() -> None:
    """Test notify handler sends command output."""
    _, mod = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"stdout": "hello world", "return_code": 0}

    result = await mod.notify(ctx)

    assert result["sent"] is True
    ctx.notify.send.assert_awaited_once()
    sent_msg = ctx.notify.send.call_args[0][0]
    assert "hello world" in sent_msg
    assert "rc=0" in sent_msg


@pytest.mark.asyncio
async def test_notify_no_output() -> None:
    """Test notify returns not sent when output is empty."""
    _, mod = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"stdout": "", "stderr": ""}

    result = await mod.notify(ctx)

    assert result["sent"] is False


@pytest.mark.asyncio
async def test_notify_truncates_long_output() -> None:
    """Test notify truncates output longer than 4000 chars."""
    _, mod = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"stdout": "x" * 5000, "return_code": 0}

    result = await mod.notify(ctx)

    assert result["sent"] is True
    sent_msg = ctx.notify.send.call_args[0][0]
    assert "truncated" in sent_msg
    assert len(sent_msg) < 5000  # verify actual truncation


@pytest.mark.asyncio
async def test_notify_short_output_not_truncated() -> None:
    """Test notify does NOT truncate output shorter than 4000 chars."""
    _, mod = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"stdout": "x" * 2000, "return_code": 0}

    result = await mod.notify(ctx)

    assert result["sent"] is True
    sent_msg = ctx.notify.send.call_args[0][0]
    assert "truncated" not in sent_msg


@pytest.mark.asyncio
async def test_notify_no_channel() -> None:
    """Test notify returns not sent when no channel available."""
    _, mod = _load_plugin()
    ctx = _make_context()
    ctx.notify = None
    ctx.input_data = {"stdout": "hello", "return_code": 0}

    result = await mod.notify(ctx)

    assert result["sent"] is False


def test_is_path_within_boundary_detects_escape(tmp_path: Path) -> None:
    """Test _is_path_within_boundary rejects symlinks that escape boundary."""
    _, mod = _load_plugin()
    boundary = tmp_path / "vault"
    boundary.mkdir()
    link = boundary / "link"
    link.symlink_to("/tmp")

    assert mod._is_path_within_boundary(link, boundary) is False


def test_is_path_within_boundary_allows_normal_path(tmp_path: Path) -> None:
    """Test _is_path_within_boundary allows paths within boundary."""
    _, mod = _load_plugin()
    boundary = tmp_path / "vault"
    subdir = boundary / "notes"
    subdir.mkdir(parents=True)

    assert mod._is_path_within_boundary(subdir, boundary) is True


@pytest.mark.asyncio
async def test_execute_symlink_chain_escape_blocked(tmp_path: Path) -> None:
    """Test that chained symlinks escaping vault boundary are blocked."""
    execute_fn, _ = _load_plugin()

    # Create chain: link_a -> link_b -> outside (outside vault)
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link_b = vault / "link_b"
    link_b.symlink_to(outside)
    link_a = vault / "link_a"
    link_a.symlink_to(link_b)

    ctx = _make_context(vault_root=vault)
    ctx.input_data = {"command": "echo hello", "working_dir": str(link_a)}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "outside vault/tmp" in result.get("error", "")


@pytest.mark.asyncio
async def test_invalid_sandbox_mode_defaults_to_vault_only(tmp_path: Path) -> None:
    """Test that invalid sandbox_mode values default to vault_only behavior."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)
    ctx.credentials = {"sandbox_mode": "INVALID_MODE", "allowed_commands": "echo"}
    ctx.config.safe_mode = False

    # With invalid mode defaulting to vault_only, paths outside vault should be blocked
    ctx.input_data = {"command": "echo hello", "working_dir": "/etc"}
    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "outside vault/tmp" in result.get("error", "")
