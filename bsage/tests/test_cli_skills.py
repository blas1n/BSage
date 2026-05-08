"""Tests for ``bsage skills`` Typer sub-app (TASK-004 + REVIEW-004A).

The sub-app wraps the skills REST surface:

* ``list``  → ``GET  /api/skills``
* ``run``   → ``POST /api/run/{name}``

There are deliberately no ``add``/``update``/``delete`` commands —
skills are file-backed YAML+Markdown and authored via git under
``skills/``. Exposing write-via-HTTP would create a prompt-injection
vector since skills are LLM system prompts that the agent then
executes. REVIEW-004A resolved this by removing the planned-payload
stubs that earlier shipped under TASK-004.

Help-text checks strip ANSI escapes per the Phase 3 lesson — rich/Typer
splits flag tokens across colour escapes in non-TTY CI runs and a plain
string match would fail even though the flag is rendered.
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
    """Replace ``build_client`` with a recording mock for HTTP-backed cmds."""

    client = MagicMock(name="CliHttpClient")
    client.aclose = AsyncMock(return_value=None)
    client.get = AsyncMock()
    client.post = AsyncMock()

    monkeypatch.setattr(
        "bsage.cli.commands.skills.build_client",
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


def test_skills_subapp_help_lists_supported_subcommands(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, ["skills", "--help"])
    assert result.exit_code == 0, result.stderr
    plain = _strip_ansi(result.stdout)
    for sub in ("list", "run"):
        assert sub in plain, f"missing skills subcommand {sub!r}:\n{plain}"


def test_skills_subapp_does_not_expose_write_commands(runner: CliRunner) -> None:
    """Authoring is git-based — REST mutation surface is intentionally absent.

    REVIEW-004A: dropping ``add``/``update``/``delete`` keeps prompt-
    injection out of the LLM system-prompt surface. Pin so a future
    refactor doesn't quietly re-introduce them.
    """
    from bsage.cli.main import app

    for sub in ("add", "update", "delete"):
        result = runner.invoke(app, ["skills", sub, "demo"])
        assert result.exit_code != 0, f"{sub!r} should be rejected: {result.stdout}"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_skills_list_emits_json(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(
        200,
        [{"name": "weekly-digest", "category": "process", "enabled": True}],
    )
    result = runner.invoke(app, _base_args("skills", "list"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_awaited_once_with("/api/skills")
    payload = json.loads(result.stdout)
    assert payload[0]["name"] == "weekly-digest"


def test_skills_list_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("--dry-run", "skills", "list"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_not_called()
    plain = _strip_ansi(result.stdout)
    assert "/api/skills" in plain
    assert "GET" in plain


def test_skills_list_http_error_friendly(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(403, {"detail": "forbidden"})
    result = runner.invoke(app, _base_args("skills", "list"))
    assert result.exit_code == 1
    assert "403" in result.stderr
    assert "forbidden" in result.stderr
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_skills_run_posts_to_run_endpoint(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.post.return_value = _resp(200, {"name": "weekly-digest", "result": {}})
    result = runner.invoke(app, _base_args("skills", "run", "weekly-digest"))
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_awaited_once()
    args, kwargs = fake_client.post.call_args
    assert args[0] == "/api/run/weekly-digest"
    # default body is empty dict — backend treats missing input gracefully.
    assert kwargs.get("json") == {}


def test_skills_run_with_input_json(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.post.return_value = _resp(200, {"name": "x", "result": {}})
    result = runner.invoke(app, _base_args("skills", "run", "x", "--input", '{"q":"hello"}'))
    assert result.exit_code == 0, result.stderr
    _, kwargs = fake_client.post.call_args
    assert kwargs["json"] == {"q": "hello"}


def test_skills_run_invalid_name_is_bad_parameter(
    runner: CliRunner, fake_client: MagicMock
) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("skills", "run", "BAD_Name!"))
    assert result.exit_code != 0
    fake_client.post.assert_not_called()


def test_skills_run_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(
        app,
        _base_args("--dry-run", "skills", "run", "weekly-digest", "--input", '{"a":1}'),
    )
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_not_called()
    plain = _strip_ansi(result.stdout)
    assert "/api/run/weekly-digest" in plain
    assert '"a"' in plain


# ---------------------------------------------------------------------------
# table format with empty results doesn't crash (Phase 4 review checklist)
# ---------------------------------------------------------------------------


def test_skills_list_empty_table_does_not_crash(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, [])
    result = runner.invoke(app, ["--url", "http://x", "-o", "table", "skills", "list"])
    assert result.exit_code == 0, result.stderr
