"""End-to-end CLI ↔ Gateway integration (TASK-007).

Spins up the BSage Gateway routes against a mocked AppState, wraps the
ASGI app in an ``httpx.AsyncClient`` via ``ASGITransport``, then runs
the real ``bsage`` Typer CLI through that transport so we exercise the
full pipeline:

    Typer command → bsage.cli.commands.* → CliHttpClient → ASGITransport
    → FastAPI route → mock state → response → OutputFormatter → stdout

The assertions cover the two round-trips called out in the TASK-007
acceptance criteria:

* ``bsage settings set llm_model X`` then ``bsage settings get
  llm_model`` returns ``X`` — RuntimeConfig PATCH/GET round-trip is
  fully live (real ``RuntimeConfig`` instance, real route handlers).
* ``bsage skills list`` shows a seeded skill — there is intentionally
  no ``skills add`` (REVIEW-004A: skills are git-authored under
  ``skills/``); the listing path is live and proves the CLI's
  GET /api/skills wiring is correct end-to-end.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from bsvibe_cli_base import CliHttpClient
from fastapi import FastAPI
from typer.testing import CliRunner

from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.sync import SyncManager
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes
from bsage.tests.conftest import make_skill_meta as _make_meta

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# Fixtures: live FastAPI app + ASGITransport-backed CliHttpClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def runtime_config() -> RuntimeConfig:
    """Real RuntimeConfig — set/get round-trips run against it."""
    return RuntimeConfig(
        llm_model="anthropic/claude-sonnet-4-20250514",
        llm_api_key="",
        llm_api_base=None,
        safe_mode=True,
        disabled_entries=[],
    )


@pytest.fixture()
def state(runtime_config: RuntimeConfig) -> MagicMock:
    """Mock AppState — just enough surface for /api/skills and /api/config."""
    s = MagicMock(spec=AppState)
    s.skill_loader = MagicMock()
    s.skill_loader.load_all = AsyncMock(
        return_value={"weekly-digest": _make_meta(name="weekly-digest")}
    )
    s.skill_loader.get = MagicMock(return_value=_make_meta(name="weekly-digest"))
    s.plugin_loader = MagicMock()
    s.plugin_loader.load_all = AsyncMock(return_value={})
    s.plugin_loader.get = MagicMock(return_value=_make_meta(name="weekly-digest"))
    s.runtime_config = runtime_config
    s.sync_manager = SyncManager()
    s.danger_map = {}
    s.credential_store = MagicMock()
    s.credential_store.list_services = MagicMock(return_value=[])
    s.retriever = MagicMock()
    s.retriever.index_available = False

    async def _noop_apply() -> None:
        return None

    s.apply_canon_runtime = _noop_apply

    async def _mock_user() -> Any:
        return MagicMock(id="cli-e2e", email="cli@example.com", role="authenticated")

    s.get_current_user = _mock_user
    s.auth_provider = None
    return s


@pytest.fixture()
def fastapi_app(state: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(create_routes(state))
    return app


@pytest.fixture()
def asgi_http_client(fastapi_app: FastAPI) -> Iterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=fastapi_app)
    client = httpx.AsyncClient(transport=transport, base_url="http://bsage.test")
    try:
        yield client
    finally:
        # ASGITransport holds no OS resources; closing the client requires
        # a running loop, but each Typer subcommand opens its own via
        # asyncio.run(). Letting the client be GC'd is safe here.
        pass


@pytest.fixture()
def cli_http_client(asgi_http_client: httpx.AsyncClient) -> CliHttpClient:
    return CliHttpClient(
        base_url="http://bsage.test",
        token="e2e-token",
        http=asgi_http_client,
    )


@pytest.fixture()
def patched_build_client(
    monkeypatch: pytest.MonkeyPatch, cli_http_client: CliHttpClient
) -> CliHttpClient:
    """Patch every sub-app's ``build_client`` to share one live ASGI client.

    A no-op ``aclose`` shim wraps the shared client so subcommands closing
    their per-call client don't tear down the transport between commands.
    """
    shared = cli_http_client

    class _SharedClient:
        def __init__(self, inner: CliHttpClient) -> None:
            self._inner = inner

        async def aclose(self) -> None:  # subcommands close after each call
            return None

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    proxy = _SharedClient(shared)

    # Only sub-app modules that actually import ``build_client`` are
    # patched — ``ingest`` is a stub today (REVIEW-005A) and never builds
    # an HTTP client.
    for module in (
        "bsage.cli.commands.settings",
        "bsage.cli.commands.skills",
        "bsage.cli.commands.plugins",
        "bsage.cli.commands.canon",
        "bsage.cli.commands.garden",
    ):
        monkeypatch.setattr(f"{module}.build_client", lambda _ctx, _p=proxy: _p)

    return shared


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _base_args(*extra: str) -> list[str]:
    return [
        "--url",
        "http://bsage.test",
        "--token",
        "e2e-token",
        "-o",
        "json",
        *extra,
    ]


# ---------------------------------------------------------------------------
# settings set/get round-trip — TASK-007 acceptance criterion
# ---------------------------------------------------------------------------


def test_settings_set_then_get_round_trip(
    runner: CliRunner,
    runtime_config: RuntimeConfig,
    patched_build_client: CliHttpClient,
) -> None:
    """`bsage settings set X Y` then `bsage settings get X` returns Y."""
    from bsage.cli.main import app

    new_model = "anthropic/claude-opus-4-7"

    set_result = runner.invoke(app, _base_args("settings", "set", "llm_model", new_model))
    assert set_result.exit_code == 0, set_result.stderr
    set_payload = json.loads(set_result.stdout)
    assert set_payload["llm_model"] == new_model
    # Real RuntimeConfig was actually mutated by the PATCH handler.
    assert runtime_config.llm_model == new_model

    get_result = runner.invoke(app, _base_args("settings", "get", "llm_model"))
    assert get_result.exit_code == 0, get_result.stderr
    get_payload = json.loads(get_result.stdout)
    assert get_payload == {"llm_model": new_model}


def test_settings_get_full_snapshot_includes_seeded_field(
    runner: CliRunner,
    patched_build_client: CliHttpClient,
) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("settings", "get"))
    assert result.exit_code == 0, result.stderr
    snap = json.loads(result.stdout)
    assert "llm_model" in snap
    assert "safe_mode" in snap
    assert snap["has_llm_api_key"] is False  # empty in fixture


# ---------------------------------------------------------------------------
# skills list — proves GET /api/skills wiring is end-to-end live
# ---------------------------------------------------------------------------


def test_skills_list_shows_seeded_skill(
    runner: CliRunner,
    patched_build_client: CliHttpClient,
) -> None:
    """`bsage skills list` returns the seeded skill via real /api/skills."""
    from bsage.cli.main import app

    result = runner.invoke(app, _base_args("skills", "list"))
    assert result.exit_code == 0, result.stderr
    rows = json.loads(result.stdout)
    assert isinstance(rows, list)
    names = [row["name"] for row in rows]
    assert "weekly-digest" in names


# ---------------------------------------------------------------------------
# Smoke — `bsage --help` renders post-cutover (no click in the import graph).
# ---------------------------------------------------------------------------


def test_bsage_help_renders_with_all_subapps(runner: CliRunner) -> None:
    from bsage.cli.main import app

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.stderr
    plain = _strip_ansi(result.stdout)
    for sub in ("run", "skills", "plugins", "ingest", "garden", "canon", "settings"):
        assert sub in plain, f"missing sub-app {sub!r} in --help:\n{plain}"
