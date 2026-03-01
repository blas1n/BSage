"""Tests for the git-input plugin."""

from unittest.mock import AsyncMock, MagicMock, patch


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {"repo_path": "/fake/repo", "since_days": "7"}
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("git_input", "plugins/git-input/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


# ── execute() tests ───────────────────────────────────────────────────


async def test_execute_collects_commits() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context()

    git_log_output = (
        "abc123|Alice|feat: add foo|2026-02-25 10:00:00 +0000\n"
        "def456|Bob|fix: bar bug|2026-02-26 12:00:00 +0000"
    )

    def fake_subprocess_run(cmd, *, capture_output, text, cwd):
        result = MagicMock()
        if cmd[1] == "log":
            result.stdout = git_log_output
        else:
            # git diff --stat calls
            result.stdout = " file.py | 10 +++++++---\n"
        return result

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = await execute_fn(ctx)

    assert result == {"collected": 2}
    ctx.garden.write_seed.assert_awaited_once()
    call_args = ctx.garden.write_seed.call_args
    assert call_args[0][0] == "git"
    commits = call_args[0][1]["commits"]
    assert len(commits) == 2
    assert commits[0]["hash"] == "abc123"
    assert commits[0]["author"] == "Alice"
    assert commits[0]["message"] == "feat: add foo"
    assert commits[1]["hash"] == "def456"
    assert commits[1]["author"] == "Bob"


async def test_execute_empty_repo() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context()

    def fake_subprocess_run(cmd, *, capture_output, text, cwd):
        result = MagicMock()
        result.stdout = ""
        return result

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = await execute_fn(ctx)

    assert result == {"collected": 0}
    ctx.garden.write_seed.assert_awaited_once()
    commits = ctx.garden.write_seed.call_args[0][1]["commits"]
    assert commits == []


async def test_execute_uses_custom_since_days() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(credentials={"repo_path": "/my/repo", "since_days": "30"})

    captured_cmds: list[list[str]] = []

    def fake_subprocess_run(cmd, *, capture_output, text, cwd):
        captured_cmds.append(cmd)
        result = MagicMock()
        result.stdout = ""
        return result

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        await execute_fn(ctx)

    # The git log command should use 30 days
    log_cmd = captured_cmds[0]
    assert "--since=30 days ago" in log_cmd


async def test_execute_handles_malformed_lines() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context()

    git_log_output = (
        "abc123|Alice|feat: add foo|2026-02-25 10:00:00 +0000\n"
        "malformed-line-no-pipes\n"
        "only|two|fields\n"
        "def456|Bob|fix: bar bug|2026-02-26 12:00:00 +0000"
    )

    def fake_subprocess_run(cmd, *, capture_output, text, cwd):
        result = MagicMock()
        if cmd[1] == "log":
            result.stdout = git_log_output
        else:
            result.stdout = " file.py | 5 +++++\n"
        return result

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        result = await execute_fn(ctx)

    # Only 2 valid commits should be collected; malformed lines skipped
    assert result == {"collected": 2}
    commits = ctx.garden.write_seed.call_args[0][1]["commits"]
    assert len(commits) == 2
    assert commits[0]["hash"] == "abc123"
    assert commits[1]["hash"] == "def456"
