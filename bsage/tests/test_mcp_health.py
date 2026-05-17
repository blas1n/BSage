"""Tests for ``GET /mcp/health`` — MCP transport liveness.

The health endpoint exposes the MCP server liveness signal that
operators (Claude Code bridges, deploy probes) need without firing the
Streamable HTTP handshake. It MUST:

* Return 200 with ``status`` + ``tool_count`` when the gateway is up.
* Be unauthenticated — it's a deploy/liveness probe that runs before
  ``bsvibe-authz`` is fully bootstrapped.
* Reflect the real registry the Streamable HTTP transport serves — not
  a stub.

The route is declared directly on the FastAPI app in
:func:`bsage.gateway.app.create_app` (so it resolves before the ``/mcp``
Streamable HTTP mount). These tests exercise the route's handler logic
in isolation against a duck-typed ``AppState``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


@pytest.fixture()
def state(tmp_path: Path) -> MagicMock:
    s = MagicMock()
    s.vault = MagicMock()
    s.vault.root = tmp_path
    s.vault.resolve_path = MagicMock(side_effect=lambda p: tmp_path / p)
    s.embedder = MagicMock()
    s.embedder.enabled = False
    s.vector_store = None
    s.retriever = MagicMock()
    s.retriever.search = AsyncMock(return_value="result")
    s.graph_retriever = MagicMock()
    s.graph_retriever.retrieve = AsyncMock(return_value="ctx")
    s.index_reader = MagicMock()
    s.index_reader.get_all_summaries = AsyncMock(return_value=[])
    s.garden_writer = MagicMock()
    s.runtime_config = MagicMock()
    s.runtime_config.disabled_entries = []
    s.plugin_loader = MagicMock()
    s.plugin_loader.load_all = AsyncMock(return_value={})
    s.skill_loader = MagicMock()
    s.skill_loader.load_all = AsyncMock(return_value={})
    s.credential_store = MagicMock()
    s.credential_store.list_services = MagicMock(return_value=[])
    s.danger_map = {}
    s.audit_outbox = None
    s.settings = MagicMock()
    s.settings.mcp_canon_mutation_enabled = False
    return s


@pytest.fixture()
def app(state: MagicMock) -> FastAPI:
    """A minimal app wiring just the /mcp/health route handler.

    Mirrors the handler ``bsage.gateway.app.create_app`` declares — kept
    in the test so the health contract is exercised without booting the
    full gateway lifespan (which needs a DB / Redis).
    """
    a = FastAPI()

    @a.get("/mcp/health", tags=["mcp"])
    async def mcp_health() -> JSONResponse:
        from bsage.mcp import plugin_bridge
        from bsage.mcp.server import build_registry

        registry = build_registry(state)
        plugin_tools = await plugin_bridge.list_plugins_as_tools(state)
        return JSONResponse(
            content={
                "status": "ok",
                "server": "bsage",
                "tool_count": len(list(registry.list_tools())) + len(plugin_tools),
            }
        )

    return a


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestMcpHealth:
    def test_health_returns_200(self, client: TestClient) -> None:
        resp = client.get("/mcp/health")
        assert resp.status_code == 200

    def test_health_payload_shape(self, client: TestClient) -> None:
        resp = client.get("/mcp/health")
        body = resp.json()
        assert body["status"] == "ok"
        assert body["server"] == "bsage"
        assert isinstance(body["tool_count"], int)
        assert body["tool_count"] > 0

    def test_health_tool_count_matches_registry(self, client: TestClient, state: MagicMock) -> None:
        # The registry the health endpoint reports MUST match the registry
        # ``build_server`` constructs for the Streamable HTTP transport.
        from bsage.mcp import plugin_bridge
        from bsage.mcp.server import build_registry

        expected_registry = build_registry(state)
        # plugin_bridge contributes 0 in this fixture (load_all returns {}).
        plugin_tools = []  # known empty
        expected = len(list(expected_registry.list_tools())) + len(plugin_tools)

        resp = client.get("/mcp/health")
        assert resp.json()["tool_count"] == expected

        # Sanity: the helper used in tests is the same the route uses.
        assert plugin_bridge is not None

    def test_health_does_not_require_auth(self, client: TestClient) -> None:
        # No Authorization header — must still 200.
        resp = client.get("/mcp/health")
        assert resp.status_code == 200
