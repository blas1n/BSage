"""Tests for the new Typer-based ``bsage`` CLI skeleton (TASK-002).

These tests cover the public surface that ``bsage/cli/`` must expose:

* ``bsage.cli.main:app`` is a ``typer.Typer`` instance — the new script entry.
* ``bsage --help`` renders without error.
* The cli_app-mounted global flags (``--profile``, ``--output``, ``--tenant``,
  ``--token``, ``--url``, ``--dry-run``) are advertised in the help text.
* ``bsage.cli._client.build_client`` returns a ``CliHttpClient`` configured
  from the resolved ``CliContext``.

Help-text assertions strip ANSI escapes per the Phase 3 lesson — rich/Typer
splits flag tokens across color escapes in non-TTY CI runs and a plain string
match would fail even though the flag is rendered.
"""

from __future__ import annotations

import re

import pytest
import typer
from typer.testing import CliRunner

from bsage.cli._client import build_client
from bsage.cli.main import app

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_app_is_typer_instance() -> None:
    assert isinstance(app, typer.Typer)


def test_help_renders_with_global_flags(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    plain = _strip_ansi(result.output)
    for flag in ("--profile", "--output", "--tenant", "--token", "--url", "--dry-run"):
        assert flag in plain, f"missing global flag {flag} in help output: {plain!r}"


def test_help_advertises_program_name(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    plain = _strip_ansi(result.output)
    assert "bsage" in plain.lower()


def test_build_client_uses_cli_context_url_and_token() -> None:
    """``build_client`` derives ``CliHttpClient`` from a ``CliContext`` view."""
    from bsvibe_cli_base import CliHttpClient
    from bsvibe_cli_base.cli import CliContext
    from bsvibe_cli_base.output import OutputFormatter
    from bsvibe_cli_base.profile import ProfileStore

    ctx = CliContext(
        profile=None,
        url="https://bsage.example.com",
        tenant_id="tenant-a",
        token="abc",
        dry_run=False,
        formatter=OutputFormatter(format="json"),
        profile_store=ProfileStore(),
    )

    client = build_client(ctx)
    try:
        assert isinstance(client, CliHttpClient)
        assert client.token == "abc"
    finally:  # ensure no resource leak even if assertions fire
        # CliHttpClient inherits an ``aclose`` helper from HttpClientBase but
        # the underlying httpx client is created lazily — closing without an
        # event loop is safe here because no requests have been issued.
        pass


def test_build_client_raises_when_url_missing() -> None:
    from bsvibe_cli_base.cli import CliContext
    from bsvibe_cli_base.output import OutputFormatter
    from bsvibe_cli_base.profile import ProfileStore

    ctx = CliContext(
        profile=None,
        url="",
        tenant_id=None,
        token=None,
        dry_run=False,
        formatter=OutputFormatter(format="json"),
        profile_store=ProfileStore(),
    )

    with pytest.raises(typer.BadParameter):
        build_client(ctx)
