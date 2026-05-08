"""Tests for ``bsage settings`` Typer sub-app (TASK-006).

Sub-app surface (RuntimeConfig REST):

* ``get [KEY] [--list]`` → ``GET /api/config``. Without KEY (and without
  ``--list``) dumps the full snapshot. With KEY, emits a single
  ``{key: value}`` payload. With ``--list``, emits a list of
  ``{key, value}`` pairs — table-friendly.
* ``set KEY VALUE`` → ``PATCH /api/config`` with ``{KEY: parsed_value}``.
  ``VALUE`` is parsed as a JSON literal (``true`` / ``42`` / ``["a"]``)
  and falls back to a raw string when JSON decode fails. Unknown keys
  are rejected via ``BadParameter`` against the
  :class:`bsage.gateway.routes.ConfigUpdate` field set.

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
    client.request = AsyncMock()

    monkeypatch.setattr(
        "bsage.cli.commands.settings.build_client",
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


def _snapshot() -> dict[str, object]:
    return {
        "llm_model": "claude-opus-4-7",
        "llm_api_base": None,
        "safe_mode": True,
        "bsgateway_url": "",
        "disabled_entries": [],
        "embedding_model": "",
        "embedding_api_base": None,
        "canon_watcher_enabled": False,
        "canon_expire_enabled": False,
        "canon_lint_enabled": False,
        "canon_expire_cron": "0 * * * *",
        "canon_lint_cron": "0 0 * * 0",
        "has_llm_api_key": False,
        "has_embedding_api_key": False,
        "index_available": False,
    }


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------


def test_settings_subapp_help_lists_subcommands(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, ["settings", "--help"])
    assert result.exit_code == 0, result.stderr
    plain = _strip_ansi(result.stdout)
    for sub in ("get", "set"):
        assert sub in plain, f"missing settings subcommand {sub!r}:\n{plain}"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


def test_settings_get_no_key_emits_full_snapshot(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, _snapshot())
    result = runner.invoke(app, _base_args("settings", "get"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_awaited_once_with("/api/config")
    payload = json.loads(result.stdout)
    assert payload["llm_model"] == "claude-opus-4-7"
    assert "has_llm_api_key" in payload


def test_settings_get_specific_key(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, _snapshot())
    result = runner.invoke(app, _base_args("settings", "get", "llm_model"))
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"llm_model": "claude-opus-4-7"}


def test_settings_get_unknown_key_friendly_error(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, _snapshot())
    result = runner.invoke(app, _base_args("settings", "get", "no_such_key"))
    assert result.exit_code != 0
    assert "no_such_key" in result.stderr


def test_settings_get_list_emits_pairs(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, _snapshot())
    result = runner.invoke(app, _base_args("settings", "get", "--list"))
    assert result.exit_code == 0, result.stderr
    rows = json.loads(result.stdout)
    assert isinstance(rows, list)
    keys = {row["key"] for row in rows}
    assert "llm_model" in keys
    assert "safe_mode" in keys


def test_settings_get_list_with_key_rejected(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("settings", "get", "llm_model", "--list"))
    assert result.exit_code != 0
    fake_client.get.assert_not_called()


def test_settings_get_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("--dry-run", "settings", "get"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_not_called()
    plain = _strip_ansi(result.stdout)
    assert "/api/config" in plain


def test_settings_get_403_friendly(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(403, {"detail": "scope: bsage.config.read"})
    result = runner.invoke(app, _base_args("settings", "get"))
    assert result.exit_code == 1
    assert "403" in result.stderr
    assert "scope" in result.stderr


def test_settings_get_empty_table_does_not_crash(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, {})
    result = runner.invoke(app, ["--url", "http://x", "-o", "table", "settings", "get", "--list"])
    assert result.exit_code == 0, result.stderr


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------


def test_settings_set_string_value(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.request.return_value = _resp(200, {"llm_model": "claude-sonnet-4-6"})
    result = runner.invoke(app, _base_args("settings", "set", "llm_model", "claude-sonnet-4-6"))
    assert result.exit_code == 0, result.stderr
    method, path = fake_client.request.call_args.args[:2]
    assert method == "PATCH"
    assert path == "/api/config"
    body = fake_client.request.call_args.kwargs["json"]
    assert body == {"llm_model": "claude-sonnet-4-6"}


def test_settings_set_bool_value_parsed_as_json(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.request.return_value = _resp(200, {"safe_mode": False})
    result = runner.invoke(app, _base_args("settings", "set", "safe_mode", "false"))
    assert result.exit_code == 0, result.stderr
    body = fake_client.request.call_args.kwargs["json"]
    assert body == {"safe_mode": False}


def test_settings_set_list_value_parsed_as_json(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.request.return_value = _resp(200, {"disabled_entries": ["a", "b"]})
    result = runner.invoke(app, _base_args("settings", "set", "disabled_entries", '["a","b"]'))
    assert result.exit_code == 0, result.stderr
    body = fake_client.request.call_args.kwargs["json"]
    assert body == {"disabled_entries": ["a", "b"]}


def test_settings_set_unknown_key_rejected(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("settings", "set", "bogus_key", "x"))
    assert result.exit_code != 0
    fake_client.request.assert_not_called()


def test_settings_set_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(
        app,
        _base_args("--dry-run", "settings", "set", "llm_model", "claude-sonnet-4-6"),
    )
    assert result.exit_code == 0, result.stderr
    fake_client.request.assert_not_called()
    plain = _strip_ansi(result.stdout)
    assert "/api/config" in plain
    assert "PATCH" in plain


def test_settings_set_403_friendly(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.request.return_value = _resp(403, {"detail": "scope: bsage.config.write"})
    result = runner.invoke(app, _base_args("settings", "set", "llm_model", "claude-sonnet-4-6"))
    assert result.exit_code == 1
    assert "403" in result.stderr


def test_settings_set_secret_key_value_not_logged(
    runner: CliRunner,
    fake_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Setting a secret field must never emit the value into structlog."""
    from bsage.cli.main import app

    fake_client.request.return_value = _resp(200, {"has_llm_api_key": True})
    secret = "sk-very-private-token-xyz"
    with caplog.at_level("INFO"):
        result = runner.invoke(app, _base_args("settings", "set", "llm_api_key", secret))
    assert result.exit_code == 0, result.stderr
    combined = caplog.text + result.stdout + result.stderr
    assert secret not in combined
