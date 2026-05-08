"""Tests for ``bsage canon`` Typer sub-app (TASK-005).

Sub-app surface (canonicalization slices 1-6 — ``/api/canonicalization``):

* ``list [--kind {concepts|proposals|actions|policies}]`` →
  ``GET /api/canonicalization/concepts`` (default) or proposals/
  actions/policies/active.
* ``draft KIND --params JSON [--slug X] [--source PATH]`` →
  ``POST /api/canonicalization/actions/draft``.
* ``apply ACTION_PATH [--mode {apply|approve|reject}] [--reason TEXT]`` →
  ``POST /api/canonicalization/actions/{apply|approve|reject}``.
* ``status [--path PATH]`` — when ``--path`` is given,
  ``GET /api/canonicalization/note?path=...``; else
  ``GET /api/canonicalization/actions``.

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
        "bsage.cli.commands.canon.build_client",
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


def test_canon_subapp_help_lists_subcommands(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, ["canon", "--help"])
    assert result.exit_code == 0, result.stderr
    plain = _strip_ansi(result.stdout)
    for sub in ("list", "draft", "apply", "status"):
        assert sub in plain, f"missing canon subcommand {sub!r}:\n{plain}"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_canon_list_default_kind_concepts(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, {"items": [{"concept_id": "c1"}]})
    result = runner.invoke(app, _base_args("canon", "list"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_awaited_once_with("/api/canonicalization/concepts")


def test_canon_list_proposals(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, {"items": []})
    result = runner.invoke(app, _base_args("canon", "list", "--kind", "proposals"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_awaited_once_with("/api/canonicalization/proposals")


def test_canon_list_actions(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, {"items": []})
    result = runner.invoke(app, _base_args("canon", "list", "--kind", "actions"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_awaited_once_with("/api/canonicalization/actions")


def test_canon_list_policies(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, {"items": []})
    result = runner.invoke(app, _base_args("canon", "list", "--kind", "policies"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_awaited_once_with("/api/canonicalization/policies/active")


def test_canon_list_invalid_kind(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("canon", "list", "--kind", "bogus"))
    assert result.exit_code != 0
    fake_client.get.assert_not_called()


def test_canon_list_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("--dry-run", "canon", "list"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_not_called()
    plain = _strip_ansi(result.stdout)
    assert "/api/canonicalization/concepts" in plain


def test_canon_list_403_friendly(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(403, {"detail": "scope: bsage.canonicalization.read"})
    result = runner.invoke(app, _base_args("canon", "list"))
    assert result.exit_code == 1
    assert "403" in result.stderr
    assert "scope" in result.stderr


def test_canon_list_empty_table_does_not_crash(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, {"items": []})
    result = runner.invoke(app, ["--url", "http://x", "-o", "table", "canon", "list"])
    assert result.exit_code == 0, result.stderr


# ---------------------------------------------------------------------------
# draft
# ---------------------------------------------------------------------------


def test_canon_draft_posts_action_draft(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.post.return_value = _resp(200, {"path": "actions/merge-x.md", "status": "draft"})
    result = runner.invoke(
        app,
        _base_args(
            "canon",
            "draft",
            "merge",
            "--params",
            '{"left":"a","right":"b"}',
            "--slug",
            "merge-x",
        ),
    )
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_awaited_once()
    args, kwargs = fake_client.post.call_args
    assert args[0] == "/api/canonicalization/actions/draft"
    body = kwargs["json"]
    assert body["kind"] == "merge"
    assert body["params"] == {"left": "a", "right": "b"}
    assert body["slug"] == "merge-x"
    assert body.get("source_proposal") is None


def test_canon_draft_invalid_params_json(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("canon", "draft", "merge", "--params", "not-json"))
    assert result.exit_code != 0
    fake_client.post.assert_not_called()


def test_canon_draft_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(
        app,
        _base_args("--dry-run", "canon", "draft", "merge", "--params", '{"a":1}'),
    )
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_not_called()
    plain = _strip_ansi(result.stdout)
    assert "actions/draft" in plain


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def test_canon_apply_default_mode(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.post.return_value = _resp(
        200, {"action_path": "actions/x.md", "final_status": "applied", "affected_paths": []}
    )
    result = runner.invoke(app, _base_args("canon", "apply", "actions/x.md"))
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake_client.post.call_args
    assert args[0] == "/api/canonicalization/actions/apply"
    assert kwargs["json"] == {"action_path": "actions/x.md"}


def test_canon_apply_approve_mode(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.post.return_value = _resp(
        200, {"action_path": "actions/x.md", "final_status": "approved", "affected_paths": []}
    )
    result = runner.invoke(app, _base_args("canon", "apply", "actions/x.md", "--mode", "approve"))
    assert result.exit_code == 0, result.stderr
    args, _ = fake_client.post.call_args
    assert args[0] == "/api/canonicalization/actions/approve"


def test_canon_apply_reject_mode_includes_reason(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.post.return_value = _resp(
        200, {"action_path": "actions/x.md", "final_status": "rejected"}
    )
    result = runner.invoke(
        app,
        _base_args(
            "canon",
            "apply",
            "actions/x.md",
            "--mode",
            "reject",
            "--reason",
            "duplicate concept",
        ),
    )
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake_client.post.call_args
    assert args[0] == "/api/canonicalization/actions/reject"
    assert kwargs["json"] == {
        "action_path": "actions/x.md",
        "reason": "duplicate concept",
    }


def test_canon_apply_invalid_mode(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("canon", "apply", "actions/x.md", "--mode", "bogus"))
    assert result.exit_code != 0
    fake_client.post.assert_not_called()


def test_canon_apply_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("--dry-run", "canon", "apply", "actions/x.md"))
    assert result.exit_code == 0, result.stderr
    fake_client.post.assert_not_called()


def test_canon_apply_403_friendly(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.post.return_value = _resp(403, {"detail": "scope: bsage.canonicalization.apply"})
    result = runner.invoke(app, _base_args("canon", "apply", "actions/x.md"))
    assert result.exit_code == 1
    assert "403" in result.stderr


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_canon_status_no_path_lists_actions(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, {"items": []})
    result = runner.invoke(app, _base_args("canon", "status"))
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_awaited_once_with("/api/canonicalization/actions")


def test_canon_status_with_path_reads_note(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    fake_client.get.return_value = _resp(200, {"path": "actions/x.md", "content": "..."})
    result = runner.invoke(app, _base_args("canon", "status", "--path", "actions/x.md"))
    assert result.exit_code == 0, result.stderr
    args, kwargs = fake_client.get.call_args
    assert args[0] == "/api/canonicalization/note"
    assert kwargs.get("params") == {"path": "actions/x.md"}


def test_canon_status_dry_run_skips_http(runner: CliRunner, fake_client: MagicMock) -> None:
    from bsage.cli.main import app

    result = runner.invoke(
        app, _base_args("--dry-run", "canon", "status", "--path", "actions/x.md")
    )
    assert result.exit_code == 0, result.stderr
    fake_client.get.assert_not_called()
