"""Tests for ``bsage mcp`` Typer sub-app (Phase 7 / TASK-005).

Exposes:

* ``bsage mcp serve [--transport stdio|http] [--host H --port P]`` —
  hands off to :func:`bsage.mcp.stdio.run_stdio_server` for ``stdio``
  or to ``uvicorn.run(create_app(...))`` for ``http``. The HTTP path
  shares the same FastAPI lifespan as ``bsage run`` so the MCP server
  rides the same boot.
* ``bsage mcp list-tools`` — builds the in-process ToolRegistry and
  emits the catalog via :class:`OutputFormatter` (no HTTP required).

The global ``--dry-run`` flag short-circuits BEFORE any transport is
booted, mirroring the ``bsage run`` smoke contract.

Help-text assertions strip ANSI escapes per the Phase 3 lesson.
"""

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from bsage.cli.main import app

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _mock_settings() -> MagicMock:
    s = MagicMock()
    s.gateway_host = "127.0.0.1"
    s.gateway_port = 8000
    s.log_level = "info"
    return s


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
class TestWiring:
    def test_mcp_subapp_registered(self) -> None:
        names = {g.name for g in app.registered_groups if g.name}
        assert "mcp" in names, f"mcp sub-app missing; saw {names!r}"

    def test_mcp_help_lists_subcommands(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["mcp", "--help"])
        assert result.exit_code == 0, result.output
        plain = _strip_ansi(result.output)
        assert "serve" in plain
        assert "list-tools" in plain


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------
class TestServe:
    def test_serve_help_lists_transport_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["mcp", "serve", "--help"])
        assert result.exit_code == 0, result.output
        plain = _strip_ansi(result.output)
        assert "--transport" in plain
        assert "stdio" in plain
        assert "http" in plain

    def test_serve_dry_run_stdio_skips_runner(self, runner: CliRunner) -> None:
        with (
            patch("bsage.cli.commands.mcp.run_stdio_server") as mock_stdio,
            patch("bsage.cli.commands.mcp.uvicorn") as mock_uvicorn,
            patch("bsage.cli.commands.mcp.get_settings", return_value=_mock_settings()),
        ):
            result = runner.invoke(app, ["--dry-run", "mcp", "serve", "--transport", "stdio"])
        assert result.exit_code == 0, result.output
        mock_stdio.assert_not_called()
        mock_uvicorn.run.assert_not_called()

    def test_serve_dry_run_http_skips_uvicorn(self, runner: CliRunner) -> None:
        with (
            patch("bsage.cli.commands.mcp.uvicorn") as mock_uvicorn,
            patch("bsage.cli.commands.mcp._build_app") as mock_build,
            patch("bsage.cli.commands.mcp.get_settings", return_value=_mock_settings()),
        ):
            result = runner.invoke(app, ["--dry-run", "mcp", "serve", "--transport", "http"])
        assert result.exit_code == 0, result.output
        mock_uvicorn.run.assert_not_called()
        mock_build.assert_not_called()

    def test_serve_stdio_invokes_runner(self, runner: CliRunner) -> None:
        with (
            patch("bsage.cli.commands.mcp.asyncio") as mock_asyncio,
            patch("bsage.cli.commands.mcp.run_stdio_server") as mock_stdio,
            patch("bsage.cli.commands.mcp.get_settings", return_value=_mock_settings()),
        ):
            mock_stdio.return_value = MagicMock(name="coro")
            result = runner.invoke(app, ["mcp", "serve", "--transport", "stdio"])
        assert result.exit_code == 0, result.output
        mock_stdio.assert_called_once()
        mock_asyncio.run.assert_called_once()

    def test_serve_http_invokes_uvicorn(self, runner: CliRunner) -> None:
        fake_app = MagicMock(name="fastapi_app")
        with (
            patch("bsage.cli.commands.mcp.uvicorn") as mock_uvicorn,
            patch("bsage.cli.commands.mcp._build_app", return_value=fake_app) as mock_build,
            patch("bsage.cli.commands.mcp.get_settings", return_value=_mock_settings()),
        ):
            result = runner.invoke(
                app,
                [
                    "mcp",
                    "serve",
                    "--transport",
                    "http",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "9100",
                ],
            )
        assert result.exit_code == 0, result.output
        mock_build.assert_called_once()
        mock_uvicorn.run.assert_called_once()
        _, kwargs = mock_uvicorn.run.call_args
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["port"] == 9100

    def test_serve_default_transport_is_stdio(self, runner: CliRunner) -> None:
        with (
            patch("bsage.cli.commands.mcp.asyncio") as mock_asyncio,
            patch("bsage.cli.commands.mcp.run_stdio_server") as mock_stdio,
            patch("bsage.cli.commands.mcp.uvicorn") as mock_uvicorn,
            patch("bsage.cli.commands.mcp.get_settings", return_value=_mock_settings()),
        ):
            mock_stdio.return_value = MagicMock(name="coro")
            result = runner.invoke(app, ["mcp", "serve"])
        assert result.exit_code == 0, result.output
        mock_stdio.assert_called_once()
        mock_asyncio.run.assert_called_once()
        mock_uvicorn.run.assert_not_called()

    def test_serve_invalid_transport_errors(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["mcp", "serve", "--transport", "carrier-pigeon"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# list-tools
# ---------------------------------------------------------------------------
class TestListTools:
    def test_list_tools_emits_catalog(self, runner: CliRunner) -> None:
        # `list-tools` builds a fresh AppState so it can introspect the
        # in-process registry. Patch the AppState boot path so the test
        # stays fast and offline.
        fake_state = MagicMock()
        fake_state.settings = MagicMock(mcp_canon_mutation_enabled=False)
        fake_state.audit_outbox = None
        fake_state.plugin_loader = MagicMock()
        fake_state.initialize = AsyncMock()
        fake_state.shutdown = AsyncMock()

        async def _no_plugins(_state):
            return []

        with (
            patch(
                "bsage.cli.commands.mcp._build_state", return_value=fake_state
            ) as mock_state_factory,
            patch(
                "bsage.cli.commands.mcp.plugin_bridge.list_plugins_as_tools",
                side_effect=_no_plugins,
            ),
        ):
            result = runner.invoke(app, ["--output", "json", "mcp", "list-tools"])

        assert result.exit_code == 0, result.output
        mock_state_factory.assert_called_once()
        plain = _strip_ansi(result.output)
        # Real registry contains the canonical domain tools.
        assert "search_knowledge" in plain
        assert "bsage_settings_get" in plain  # admin tool surface present

    def test_list_tools_dry_run_skips_state(self, runner: CliRunner) -> None:
        with patch("bsage.cli.commands.mcp._build_state") as mock_state_factory:
            result = runner.invoke(app, ["--dry-run", "mcp", "list-tools"])
        assert result.exit_code == 0, result.output
        mock_state_factory.assert_not_called()

    def test_list_tools_json_output_is_valid_json(self, runner: CliRunner) -> None:
        fake_state = MagicMock()
        fake_state.settings = MagicMock(mcp_canon_mutation_enabled=False)
        fake_state.audit_outbox = None
        fake_state.initialize = AsyncMock()
        fake_state.shutdown = AsyncMock()

        async def _no_plugins(_state):
            return []

        with (
            patch("bsage.cli.commands.mcp._build_state", return_value=fake_state),
            patch(
                "bsage.cli.commands.mcp.plugin_bridge.list_plugins_as_tools",
                side_effect=_no_plugins,
            ),
        ):
            result = runner.invoke(app, ["--output", "json", "mcp", "list-tools"])
        assert result.exit_code == 0, result.output
        plain = _strip_ansi(result.output)
        parsed = json.loads(plain)
        assert isinstance(parsed, list)
        assert len(parsed) > 0
        # Each entry must carry at least name + description.
        first = parsed[0]
        assert "name" in first
        assert "description" in first


def test_mcp_typer_app_command_registered() -> None:
    """``bsage.cli.main:app`` should expose ``mcp`` after main.py imports."""
    assert isinstance(app, typer.Typer)
    names = {g.name for g in app.registered_groups if g.name}
    assert "mcp" in names
