"""Tests for ``bsage garden`` Typer sub-app (TASK-005 + REVIEW-005A).

Sub-app surface:

* ``list`` → ``GET /api/vault/tree`` — emit via :class:`OutputFormatter`.

Mutation commands (``prune`` / ``recompile``) are deliberately absent —
REVIEW-005A removed the planned-payload stubs that earlier shipped under
TASK-005. There is no REST surface for vault prune / recompile today;
exposing one without the endpoints would silently invite destructive
calls from any caller with a valid token. Operators run the in-process
pipelines via the live ``bsage`` daemon instead. The pin test below
guards against a future refactor quietly re-introducing the stubs.

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
        "bsage.cli.commands.garden.build_client",
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


def test_garden_subapp_help_lists_only_list(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, ["garden", "--help"])
    assert result.exit_code == 0, result.stderr
    plain = _strip_ansi(result.stdout)
    assert "list" in plain
    for sub in ("prune", "recompile"):
        assert sub not in plain, f"REVIEW-005A: {sub!r} must not be advertised:\n{plain}"


def test_garden_subapp_does_not_expose_mutation_commands(runner: CliRunner) -> None:
    """REVIEW-005A: mutation REST is not exposed; no CLI button without it.

    Pin so a future refactor doesn't quietly re-introduce stubs that
    look like working CLI buttons but don't actually mutate state.
    """
    from bsage.cli.main import app

    for sub in ("prune", "recompile"):
        result = runner.invoke(app, ["garden", sub])
        assert result.exit_code != 0, f"{sub!r} should be rejected: {result.stdout}"


def test_garden_list_calls_vault_tree(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, [{"path": "", "dirs": ["garden"], "files": []}])
    result = runner.invoke(app, _base_args("garden", "list"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_awaited_once_with("/api/vault/tree")
    payload = json.loads(result.stdout)
    assert payload[0]["dirs"] == ["garden"]


def test_garden_list_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("--dry-run", "garden", "list"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_not_called()


def test_garden_list_403_friendly(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(403, {"detail": "missing scope"})
    result = runner.invoke(app, _base_args("garden", "list"))
    assert result.exit_code == 1
    assert "403" in result.stderr
    assert "missing scope" in result.stderr


def test_garden_list_empty_table_does_not_crash(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, [])
    result = runner.invoke(app, ["--url", "http://x", "-o", "table", "garden", "list"])
    assert result.exit_code == 0, result.stderr
