"""Tests for ``bsage run`` Typer command (TASK-003).

The legacy Click ``bsage run`` (in :mod:`bsage._cli_legacy`) wrapped a
threaded ``uvicorn.Server`` plus an in-process ChatBridge REPL — the
"mount trick" the Phase 4 plan calls out for retirement. The new Typer
command is a clean ``uvicorn.run(create_app(...))`` call:

* honours ``--host``, ``--port``, ``--log-level``, ``--reload`` for
  back-compat with deploy scripts;
* honours the global ``--dry-run`` flag from ``cli_app`` — the test
  smoke that satisfies the acceptance criterion ("returns 0 without
  binding port");
* does NOT spin up a chat REPL — that lives in a follow-up sub-app.

Help-text assertions strip ANSI escapes per the Phase 3 lesson.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

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
    settings = MagicMock()
    settings.gateway_host = "127.0.0.1"
    settings.gateway_port = 8000
    settings.log_level = "info"
    return settings


def test_run_command_is_registered(runner: CliRunner) -> None:
    """``bsage run --help`` resolves to a real command, not 'no such command'."""
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0, result.output


def test_run_help_lists_back_compat_flags(runner: CliRunner) -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    plain = _strip_ansi(result.output)
    for flag in ("--host", "--port", "--log-level", "--reload"):
        assert flag in plain, f"missing flag {flag} in help output: {plain!r}"


def test_run_dry_run_skips_uvicorn(runner: CliRunner) -> None:
    """Global ``--dry-run`` short-circuits before uvicorn binds the port."""
    with (
        patch("bsage.cli.commands.run.uvicorn") as mock_uvicorn,
        patch("bsage.cli.commands.run._build_app") as mock_build,
        patch("bsage.cli.commands.run.get_settings", return_value=_mock_settings()),
    ):
        result = runner.invoke(app, ["--dry-run", "run"])

    assert result.exit_code == 0, result.output
    mock_uvicorn.run.assert_not_called()
    mock_build.assert_not_called()


def test_run_without_dry_run_calls_uvicorn(runner: CliRunner) -> None:
    """Live mode hands off directly to ``uvicorn.run`` with the resolved app."""
    fake_app = MagicMock(name="fastapi_app")
    with (
        patch("bsage.cli.commands.run.uvicorn") as mock_uvicorn,
        patch("bsage.cli.commands.run._build_app", return_value=fake_app) as mock_build,
        patch("bsage.cli.commands.run.get_settings", return_value=_mock_settings()),
    ):
        result = runner.invoke(app, ["run"])

    assert result.exit_code == 0, result.output
    mock_build.assert_called_once()
    mock_uvicorn.run.assert_called_once()
    args, kwargs = mock_uvicorn.run.call_args
    # First positional or `app=` kwarg must be the FastAPI app instance.
    if args:
        assert args[0] is fake_app
    else:
        assert kwargs.get("app") is fake_app
    assert kwargs.get("host") == "127.0.0.1"
    assert kwargs.get("port") == 8000
    assert kwargs.get("log_level") == "info"
    assert kwargs.get("reload") is False


def test_run_overrides_host_port_log_level_reload(runner: CliRunner) -> None:
    fake_app = MagicMock(name="fastapi_app")
    with (
        patch("bsage.cli.commands.run.uvicorn") as mock_uvicorn,
        patch("bsage.cli.commands.run._build_app", return_value=fake_app),
        patch("bsage.cli.commands.run.get_settings", return_value=_mock_settings()),
    ):
        result = runner.invoke(
            app,
            [
                "run",
                "--host",
                "0.0.0.0",
                "--port",
                "9001",
                "--log-level",
                "debug",
                "--reload",
            ],
        )

    assert result.exit_code == 0, result.output
    _, kwargs = mock_uvicorn.run.call_args
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9001
    assert kwargs["log_level"] == "debug"
    assert kwargs["reload"] is True


def test_run_dry_run_emits_plan_payload(runner: CliRunner) -> None:
    """``--dry-run`` should emit a structured plan via the formatter so AI
    agents (and operators) can ``| jq`` it just like every other sub-app."""
    with (
        patch("bsage.cli.commands.run.uvicorn"),
        patch("bsage.cli.commands.run._build_app"),
        patch("bsage.cli.commands.run.get_settings", return_value=_mock_settings()),
    ):
        result = runner.invoke(
            app,
            ["--dry-run", "--output", "json", "run", "--port", "9999"],
        )

    assert result.exit_code == 0, result.output
    plain = _strip_ansi(result.output)
    assert "9999" in plain
    assert "127.0.0.1" in plain or "0.0.0.0" in plain
    assert "dry_run" in plain or '"plan"' in plain or "uvicorn" in plain.lower()


def test_run_no_typer_bad_parameter_when_url_missing(runner: CliRunner) -> None:
    """``bsage run`` is HTTP-free — must NOT raise the missing-URL guard
    that ``build_client`` enforces for HTTP sub-apps. Smoke that the
    command is reachable with an empty URL profile context."""
    with (
        patch("bsage.cli.commands.run.uvicorn"),
        patch("bsage.cli.commands.run._build_app"),
        patch("bsage.cli.commands.run.get_settings", return_value=_mock_settings()),
    ):
        result = runner.invoke(app, ["--dry-run", "run"])
    # An exit code of 2 with "BadParameter" would mean we tripped the
    # build_client URL guard — should not happen for an in-process command.
    assert "BadParameter" not in (result.output or "")
    assert result.exit_code == 0


def test_run_dry_run_does_not_import_create_app(runner: CliRunner) -> None:
    """The plan calls out dropping the mount trick: under ``--dry-run`` we
    must not even construct the FastAPI app — keeps the smoke fast and
    avoids importing optional deps just to print a plan."""
    # Note: ``_build_app`` (which wraps create_app + Settings) is the
    # boundary; if it is invoked the smoke test slows down materially
    # and may fail in CI sandboxes without LLM creds. Other tests assert
    # the live path; this one nails the dry-run boundary.
    sentinel = MagicMock(side_effect=AssertionError("must not be called"))
    with (
        patch("bsage.cli.commands.run.uvicorn"),
        patch("bsage.cli.commands.run._build_app", new=sentinel),
        patch("bsage.cli.commands.run.get_settings", return_value=_mock_settings()),
    ):
        result = runner.invoke(app, ["--dry-run", "run"])
    assert result.exit_code == 0, result.output


def test_run_typer_app_command_registered() -> None:
    """``bsage.cli.main:app`` should expose ``run`` after main.py imports."""
    # Invariant for downstream sub-apps that may want to introspect.
    assert isinstance(app, typer.Typer)
    names = {cmd.name for cmd in app.registered_commands if cmd.name}
    # Typer auto-derives command names from function names when not given.
    derived = {
        (cmd.name or (cmd.callback.__name__ if cmd.callback else ""))
        for cmd in app.registered_commands
    }
    assert "run" in names or "run" in derived, f"run command missing; saw {derived!r}"
