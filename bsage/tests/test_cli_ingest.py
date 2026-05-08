"""Tests for ``bsage ingest`` Typer sub-app (TASK-005).

The ingest pipeline lives in :mod:`bsage.garden.ingest_compiler`
(``IngestCompiler.compile_batch``) — there is *no* ``/api/ingest/...``
or ``/api/compile_batch`` REST surface in the current Gateway. So
``bsage ingest run`` / ``bsage ingest status`` ship as planned-payload
stubs that mirror the ``skills add/update/delete`` precedent: they
emit a machine-readable preview via the formatter and exit 0, and a
follow-up REVIEW task tracks promoting them to live REST once the
endpoint lands.

Help-text checks strip ANSI escapes per the Phase 3 lesson — rich/Typer
splits flag tokens across colour escapes in non-TTY CI runs and a plain
string match would fail even though the flag is rendered.
"""

from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _base_args(*extra: str) -> list[str]:
    return ["--url", "http://bsage.test", "--token", "tok", "-o", "json", *extra]


def test_ingest_subapp_help_lists_subcommands(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0, result.stderr
    plain = _strip_ansi(result.stdout)
    for sub in ("run", "status"):
        assert sub in plain, f"missing ingest subcommand {sub!r}:\n{plain}"


def test_ingest_run_emits_planned_payload(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(
        app,
        _base_args("ingest", "run", "--source", "seeds/telegram-input"),
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("stub") is True
    assert payload.get("source") == "seeds/telegram-input"
    assert payload.get("action") == "run"


def test_ingest_run_default_source_is_none(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("ingest", "run"))
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("source") is None


def test_ingest_status_emits_planned_payload(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("ingest", "status", "--task", "abc-123"))
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("stub") is True
    assert payload.get("task") == "abc-123"
    assert payload.get("action") == "status"


def test_ingest_status_default_task_none(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("ingest", "status"))
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("task") is None
