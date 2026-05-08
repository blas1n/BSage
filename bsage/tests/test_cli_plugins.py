"""Tests for ``bsage plugins`` Typer sub-app (TASK-004).

Sub-app surface:

* ``list``    → ``GET  /api/plugins``
* ``install`` → in-process ``uv pip install -r <plugin>/requirements.txt``.
* ``enable``  → ``POST /api/entries/{name}/toggle`` *only when needed*.
* ``disable`` → ``POST /api/entries/{name}/toggle`` *only when needed*.

The toggle endpoint is a flip, not an absolute set, so ``enable``/``disable``
first probe ``GET /api/plugins`` (and ``/api/skills``) to find the current
``enabled`` field; if already in the target state we emit a no-op result and
skip the toggle. This keeps `bsage plugins enable foo` idempotent — running
it twice never silently re-disables the entry.

Help-text checks strip ANSI escapes per the Phase 3 lesson.
"""

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from typer.testing import CliRunner

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    client = MagicMock(name="CliHttpClient")
    client.aclose = AsyncMock(return_value=None)
    client.get = AsyncMock()
    client.post = AsyncMock()

    monkeypatch.setattr(
        "bsage.cli.commands.plugins.build_client",
        lambda ctx: client,
    )
    return client


def _resp(status_code: int = 200, payload: object | None = None) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.json.return_value = payload
    r.text = json.dumps(payload, default=str) if payload is not None else ""
    return r


def _base_args(*extra: str) -> list[str]:
    return ["--url", "http://bsage.test", "--token", "tok", "-o", "json", *extra]


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------


def test_plugins_subapp_help_lists_all_subcommands(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, ["plugins", "--help"])
    assert result.exit_code == 0, result.stderr
    plain = _strip_ansi(result.stdout)
    for sub in ("list", "install", "enable", "disable"):
        assert sub in plain, f"missing plugins subcommand {sub!r}:\n{plain}"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_plugins_list_emits_json(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(
        200,
        [{"name": "telegram-input", "category": "input", "enabled": True}],
    )
    result = runner.invoke(app, _base_args("plugins", "list"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_awaited_once_with("/api/plugins")
    payload = json.loads(result.stdout)
    assert payload[0]["name"] == "telegram-input"


def test_plugins_list_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("--dry-run", "plugins", "list"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_not_called()


def test_plugins_list_403_friendly(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(403, {"detail": "missing scope"})
    result = runner.invoke(app, _base_args("plugins", "list"))
    assert result.exit_code == 1
    assert "403" in result.stderr
    assert "missing scope" in result.stderr


def test_plugins_list_empty_table_does_not_crash(runner: CliRunner, fake_client: MagicMock) -> None:
    """`-o table` with an empty registry must not crash the formatter (REVIEW-001)."""
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, [])
    result = runner.invoke(app, ["--url", "http://x", "-o", "table", "plugins", "list"])
    assert result.exit_code == 0, result.stderr


# ---------------------------------------------------------------------------
# install (in-process subprocess)
# ---------------------------------------------------------------------------


def test_plugins_install_runs_uv_pip(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from bsage.cli.main import app

    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "demo"
    plugin_dir.mkdir(parents=True)
    req = plugin_dir / "requirements.txt"
    req.write_text("httpx>=0.27\n")

    fake_settings = MagicMock()
    fake_settings.plugins_dir = plugins_dir
    monkeypatch.setattr("bsage.cli.commands.plugins.get_settings", lambda: fake_settings)

    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = "ok"
    completed.stderr = ""
    fake_run = MagicMock(return_value=completed)
    monkeypatch.setattr("bsage.cli.commands.plugins.subprocess.run", fake_run)

    result = runner.invoke(app, _base_args("plugins", "install", "demo"))
    assert result.exit_code == 0, result.stderr
    fake_run.assert_called_once()
    cmd = fake_run.call_args.args[0]
    assert cmd[:3] == ["uv", "pip", "install"]
    assert "-r" in cmd
    assert str(req) in cmd


def test_plugins_install_no_requirements(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from bsage.cli.main import app

    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "demo"
    plugin_dir.mkdir(parents=True)

    fake_settings = MagicMock()
    fake_settings.plugins_dir = plugins_dir
    monkeypatch.setattr("bsage.cli.commands.plugins.get_settings", lambda: fake_settings)
    fake_run = MagicMock()
    monkeypatch.setattr("bsage.cli.commands.plugins.subprocess.run", fake_run)

    result = runner.invoke(app, _base_args("plugins", "install", "demo"))
    assert result.exit_code == 0, result.stderr
    fake_run.assert_not_called()


def test_plugins_install_missing_dir(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from bsage.cli.main import app

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fake_settings = MagicMock()
    fake_settings.plugins_dir = plugins_dir
    monkeypatch.setattr("bsage.cli.commands.plugins.get_settings", lambda: fake_settings)

    result = runner.invoke(app, _base_args("plugins", "install", "ghost"))
    assert result.exit_code != 0
    assert "ghost" in result.stderr


def test_plugins_install_dry_run_skips_subprocess(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from bsage.cli.main import app

    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "requirements.txt").write_text("httpx\n")

    fake_settings = MagicMock()
    fake_settings.plugins_dir = plugins_dir
    monkeypatch.setattr("bsage.cli.commands.plugins.get_settings", lambda: fake_settings)

    fake_run = MagicMock()
    monkeypatch.setattr("bsage.cli.commands.plugins.subprocess.run", fake_run)

    result = runner.invoke(app, _base_args("--dry-run", "plugins", "install", "demo"))
    assert result.exit_code == 0, result.stderr
    fake_run.assert_not_called()
    plain = _strip_ansi(result.stdout)
    assert "demo" in plain


def test_plugins_install_invalid_name(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("plugins", "install", "BAD!"))
    assert result.exit_code != 0


def test_plugins_install_subprocess_failure_surfaces(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from bsage.cli.main import app

    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "requirements.txt").write_text("httpx\n")
    fake_settings = MagicMock()
    fake_settings.plugins_dir = plugins_dir
    monkeypatch.setattr("bsage.cli.commands.plugins.get_settings", lambda: fake_settings)

    completed = MagicMock()
    completed.returncode = 1
    completed.stdout = ""
    completed.stderr = "resolution failure"
    monkeypatch.setattr("bsage.cli.commands.plugins.subprocess.run", lambda *a, **kw: completed)

    result = runner.invoke(app, _base_args("plugins", "install", "demo"))
    assert result.exit_code != 0
    assert "resolution failure" in result.stderr


# ---------------------------------------------------------------------------
# enable / disable (idempotent toggle)
# ---------------------------------------------------------------------------


def test_plugins_enable_already_enabled_is_noop(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.side_effect = [
        _resp(200, [{"name": "demo", "enabled": True}]),  # /api/plugins
        _resp(200, []),  # /api/skills
    ]
    result = runner.invoke(app, _base_args("plugins", "enable", "demo"))
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_not_called()
    payload = json.loads(result.stdout)
    assert payload["enabled"] is True
    assert payload["changed"] is False


def test_plugins_enable_when_disabled_calls_toggle(
    runner: CliRunner, fake_client: MagicMock
) -> None:
    from bsage.cli.main import app

    fake_client.get.side_effect = [
        _resp(200, [{"name": "demo", "enabled": False}]),
        _resp(200, []),
    ]
    fake_client.post.return_value = _resp(200, {"name": "demo", "enabled": True})

    result = runner.invoke(app, _base_args("plugins", "enable", "demo"))
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_awaited_once_with("/api/entries/demo/toggle")
    payload = json.loads(result.stdout)
    assert payload["enabled"] is True
    assert payload["changed"] is True


def test_plugins_disable_when_enabled_calls_toggle(
    runner: CliRunner, fake_client: MagicMock
) -> None:
    from bsage.cli.main import app

    fake_client.get.side_effect = [
        _resp(200, [{"name": "demo", "enabled": True}]),
        _resp(200, []),
    ]
    fake_client.post.return_value = _resp(200, {"name": "demo", "enabled": False})

    result = runner.invoke(app, _base_args("plugins", "disable", "demo"))
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_awaited_once_with("/api/entries/demo/toggle")


def test_plugins_enable_unknown_entry_is_404(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.side_effect = [
        _resp(200, []),
        _resp(200, []),
    ]
    result = runner.invoke(app, _base_args("plugins", "enable", "ghost"))
    assert result.exit_code != 0
    fake_client.post.assert_not_called()
    assert "ghost" in result.stderr


def test_plugins_enable_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("--dry-run", "plugins", "enable", "demo"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_not_called()
    fake_client.post.assert_not_called()
    plain = _strip_ansi(result.stdout)
    assert "demo" in plain
    assert "toggle" in plain.lower() or "/api/entries/demo" in plain


def test_plugins_enable_invalid_name(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("plugins", "enable", "BAD!"))
    assert result.exit_code != 0
