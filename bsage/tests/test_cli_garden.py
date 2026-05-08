"""Tests for ``bsage garden`` Typer sub-app (TASK-005).

Sub-app surface:

* ``list``      → ``GET /api/vault/tree`` — emit via :class:`OutputFormatter`.
* ``prune``     → *stub* (no REST surface). Mirrors the
  ``skills add/update/delete`` precedent: emits a planned-payload
  preview and exits 0; follow-up REVIEW promotes to live REST.
* ``recompile`` → *stub* (no REST surface).

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


def test_garden_subapp_help_lists_subcommands(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, ["garden", "--help"])
    assert result.exit_code == 0, result.stderr
    plain = _strip_ansi(result.stdout)
    for sub in ("list", "prune", "recompile"):
        assert sub in plain, f"missing garden subcommand {sub!r}:\n{plain}"


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


def test_garden_prune_emits_planned_payload(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("garden", "prune", "--older-than", "30"))
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_not_called()
    payload = json.loads(result.stdout)
    assert payload.get("stub") is True
    assert payload.get("older_than_days") == 30
    assert payload.get("action") == "prune"


def test_garden_prune_default_older_than_none(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("garden", "prune"))
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("older_than_days") is None


def test_garden_recompile_emits_planned_payload(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("garden", "recompile", "--ids", "a,b,c"))
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_not_called()
    payload = json.loads(result.stdout)
    assert payload.get("stub") is True
    assert payload.get("ids") == ["a", "b", "c"]
    assert payload.get("action") == "recompile"


def test_garden_recompile_no_ids(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("garden", "recompile"))
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("ids") == []
