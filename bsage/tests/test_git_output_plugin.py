"""Tests for the git-output plugin."""

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch


def _load_plugin():
    """Import the plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("git_output", "plugins/git-output/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
    config: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {}
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    ctx.garden.write_action = AsyncMock()
    ctx.config = config or {}
    return ctx


def _make_completed_process(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ── execute() tests ───────────────────────────────────────────────────


async def test_execute_commits_and_pushes() -> None:
    execute_fn = _load_plugin()

    ctx = _make_context(
        input_data={"source": "telegram-input", "event_type": "seed"},
        credentials={"repo_path": "/tmp/repo", "auto_push": "true"},
        config={"vault_path": "/tmp/repo"},
    )

    def mock_subprocess_run(cmd, **kwargs):
        git_subcommand = cmd[1] if len(cmd) > 1 else ""
        if git_subcommand == "status":
            return _make_completed_process(stdout="M file.md\n")
        if git_subcommand == "commit":
            return _make_completed_process(stdout="1 file changed")
        if git_subcommand == "push":
            return _make_completed_process()
        # add
        return _make_completed_process()

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        result = await execute_fn(ctx)

    assert result["committed"] is True
    assert result["pushed"] is True
    assert "telegram-input" in result["message"]


async def test_execute_nothing_to_commit() -> None:
    execute_fn = _load_plugin()

    ctx = _make_context(
        input_data={"source": "test", "event_type": "seed"},
        credentials={"repo_path": "/tmp/repo"},
        config={"vault_path": "/tmp/repo"},
    )

    def mock_subprocess_run(cmd, **kwargs):
        git_subcommand = cmd[1] if len(cmd) > 1 else ""
        if git_subcommand == "status":
            # Empty porcelain output means nothing to commit
            return _make_completed_process(stdout="")
        return _make_completed_process()

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        result = await execute_fn(ctx)

    assert result["committed"] is False
    assert result["reason"] == "nothing to commit"


async def test_execute_push_disabled() -> None:
    execute_fn = _load_plugin()

    ctx = _make_context(
        input_data={"source": "test", "event_type": "seed"},
        credentials={"repo_path": "/tmp/repo", "auto_push": "false"},
        config={"vault_path": "/tmp/repo"},
    )

    calls: list[list[str]] = []

    def mock_subprocess_run(cmd, **kwargs):
        calls.append(cmd)
        git_subcommand = cmd[1] if len(cmd) > 1 else ""
        if git_subcommand == "status":
            return _make_completed_process(stdout="M file.md\n")
        if git_subcommand == "commit":
            return _make_completed_process(stdout="1 file changed")
        return _make_completed_process()

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        result = await execute_fn(ctx)

    assert result["committed"] is True
    assert result["pushed"] is False
    # Verify no push command was issued
    git_subcommands = [c[1] for c in calls if len(c) > 1]
    assert "push" not in git_subcommands


async def test_execute_commit_failure() -> None:
    execute_fn = _load_plugin()

    ctx = _make_context(
        input_data={"source": "test", "event_type": "seed"},
        credentials={"repo_path": "/tmp/repo"},
        config={"vault_path": "/tmp/repo"},
    )

    def mock_subprocess_run(cmd, **kwargs):
        git_subcommand = cmd[1] if len(cmd) > 1 else ""
        if git_subcommand == "status":
            return _make_completed_process(stdout="M file.md\n")
        if git_subcommand == "commit":
            return _make_completed_process(returncode=1, stderr="error: commit failed")
        return _make_completed_process()

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        result = await execute_fn(ctx)

    assert result["committed"] is False
    assert "error" in result
    assert "commit failed" in result["error"]
