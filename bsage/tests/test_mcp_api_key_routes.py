"""Tests for the MCP API key REST endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.gateway.dependencies import AppState
from bsage.gateway.mcp_api_keys_routes import create_mcp_api_keys_routes
from bsage.mcp.api_keys import MCPAPIKeyStore


@pytest.fixture()
def state(tmp_path: Path) -> MagicMock:
    s = MagicMock(spec=AppState)

    async def _principal():
        p = MagicMock()
        p.active_tenant_id = "t1"
        p.id = "user-1"
        return p

    s.get_current_user = _principal
    s.mcp_api_keys = MCPAPIKeyStore(tmp_path / "mcp_api_keys.json")
    return s


@pytest.fixture()
def client(state: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(create_mcp_api_keys_routes(state))
    return TestClient(app)


class TestCreate:
    def test_returns_raw_token_once(self, client: TestClient) -> None:
        r = client.post("/api/mcp/api-keys", json={"name": "cursor"})
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["token"].startswith("bsg_mcp_")
        assert data["name"] == "cursor"
        assert "id" in data

    def test_requires_name(self, client: TestClient) -> None:
        r = client.post("/api/mcp/api-keys", json={})
        assert r.status_code == 422

    def test_rejects_empty_name(self, client: TestClient) -> None:
        r = client.post("/api/mcp/api-keys", json={"name": ""})
        assert r.status_code == 422


class TestList:
    def test_list_excludes_token_hash(self, client: TestClient) -> None:
        client.post("/api/mcp/api-keys", json={"name": "first"})
        client.post("/api/mcp/api-keys", json={"name": "second"})
        r = client.get("/api/mcp/api-keys")
        assert r.status_code == 200
        keys = r.json()
        assert len(keys) == 2
        for k in keys:
            assert "token" not in k
            assert "hashed_token" not in k
            assert {"id", "name", "created_at", "last_used_at", "revoked_at"}.issubset(k.keys())

    def test_list_filters_by_active_tenant(self, client: TestClient, state: MagicMock) -> None:
        client.post("/api/mcp/api-keys", json={"name": "t1-key"})
        # Cross-tenant noise — directly create on a different tenant
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            state.mcp_api_keys.create(name="t2-key", tenant_id="t2")
        )
        r = client.get("/api/mcp/api-keys")
        names = [k["name"] for k in r.json()]
        assert names == ["t1-key"]


class TestRevoke:
    def test_revoke_marks_inactive(self, client: TestClient) -> None:
        created = client.post("/api/mcp/api-keys", json={"name": "x"}).json()
        r = client.delete(f"/api/mcp/api-keys/{created['id']}")
        assert r.status_code == 204
        # No longer in the active list
        active = client.get("/api/mcp/api-keys").json()
        assert all(k["id"] != created["id"] for k in active)

    def test_revoke_unknown_404(self, client: TestClient) -> None:
        r = client.delete("/api/mcp/api-keys/nope")
        assert r.status_code == 404
