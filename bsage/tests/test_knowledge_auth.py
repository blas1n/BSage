"""Tests for auth enforcement on /api/knowledge/* endpoints.

Verifies that knowledge endpoints require valid JWT when auth is enabled,
and that service accounts (e.g. bsnexus-planner) are allowed via both
JWT and X-Service-Key header.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from bsvibe_auth import BSVibeUser, SupabaseAuthProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.sync import SyncManager
from bsage.gateway.auth import create_get_current_user
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes


def _build_vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "vault"
    facts_dir = vault_root / "facts"
    facts_dir.mkdir(parents=True)
    (facts_dir / "test-fact.md").write_text(
        "---\ntype: fact\nstatus: seed\ntags:\n  - test\n"
        "captured_at: '2026-03-01'\n---\n# Test Fact\n\nTest content.\n"
    )
    return vault_root


def _make_mock_provider() -> MagicMock:
    """Mock SupabaseAuthProvider that validates known test tokens."""
    provider = MagicMock(spec=SupabaseAuthProvider)

    async def _verify(token: str) -> BSVibeUser:
        if token == "valid-jwt-token":
            return BSVibeUser(id="user-1", email="user@test.com", role="authenticated")
        if token == "service-jwt-token":
            return BSVibeUser(
                id="bsnexus-planner",
                email="svc@bsvibe.dev",
                role="service_role",
            )
        from bsvibe_auth import AuthError

        raise AuthError("Invalid token")

    provider.verify_token = _verify
    return provider


def _make_state(
    vault_root: Path,
    *,
    auth_provider: MagicMock | None = None,
    service_api_keys: dict[str, str] | None = None,
) -> MagicMock:
    state = MagicMock(spec=AppState)
    state.skill_loader = MagicMock()
    state.skill_loader.load_all = AsyncMock(return_value={})
    state.plugin_loader = MagicMock()
    state.plugin_loader.load_all = AsyncMock(return_value={})
    state.agent_loop = MagicMock()
    state.vault = MagicMock()
    state.vault.root = vault_root
    state.vault.read_notes = AsyncMock(return_value=[])
    state.runtime_config = RuntimeConfig(
        llm_model="anthropic/claude-sonnet-4-20250514",
        llm_api_key="test-key",
        llm_api_base=None,
        safe_mode=True,
        disabled_entries=[],
    )
    state.sync_manager = SyncManager()
    state.danger_map = {}
    state.credential_store = MagicMock()
    state.credential_store.list_services = MagicMock(return_value=[])
    state.retriever = MagicMock()
    state.retriever.index_available = False
    state.embedder = MagicMock()
    state.embedder.enabled = False
    state.vector_store = MagicMock()
    state.prompt_registry = MagicMock(spec=PromptRegistry)
    state.prompt_registry.get = MagicMock(return_value="You are BSage.")
    state.prompt_registry.render = MagicMock(return_value="Chat instructions here.")
    state.chat_bridge = AsyncMock()
    state.garden_writer = AsyncMock()
    state.garden_writer.write_garden = AsyncMock(
        return_value=vault_root / "ideas" / "test.md",
    )

    # Ontology mock
    ontology = MagicMock()
    ontology.get_entity_types.return_value = {
        "idea": {"folder": "ideas/", "knowledge_layer": "semantic"},
        "insight": {"folder": "insights/", "knowledge_layer": "semantic"},
        "fact": {"folder": "facts/", "knowledge_layer": "semantic"},
        "task": {"folder": "tasks/", "knowledge_layer": "episodic"},
    }
    state.ontology = ontology

    state.auth_provider = auth_provider
    state.get_current_user = create_get_current_user(
        provider=auth_provider,
        service_api_keys=service_api_keys,
    )
    return state


@pytest.fixture()
def vault_root(tmp_path):
    return _build_vault(tmp_path)


@pytest.fixture()
def auth_client(vault_root):
    """Client with JWT auth enabled, no service keys."""
    state = _make_state(vault_root, auth_provider=_make_mock_provider())
    app = FastAPI()
    app.include_router(create_routes(state))
    return TestClient(app)


@pytest.fixture()
def service_key_client(vault_root):
    """Client with JWT auth + service API keys enabled."""
    state = _make_state(
        vault_root,
        auth_provider=_make_mock_provider(),
        service_api_keys={"bsnexus-planner": "secret-service-key-123"},
    )
    app = FastAPI()
    app.include_router(create_routes(state))
    return TestClient(app)


@pytest.fixture()
def open_client(vault_root):
    """Client with auth disabled (anonymous access)."""
    state = _make_state(vault_root, auth_provider=None)
    app = FastAPI()
    app.include_router(create_routes(state))
    return TestClient(app)


class TestKnowledgeAuthEnforcement:
    """All knowledge endpoints return 401 without valid credentials."""

    def test_notify_unauthenticated_returns_401(self, auth_client):
        resp = auth_client.post("/api/notify", json={"message": "test"})
        assert resp.status_code == 401

    def test_notify_invalid_token_returns_401(self, auth_client):
        resp = auth_client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401

    def test_notify_valid_token_returns_200(self, auth_client):
        resp = auth_client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer valid-jwt-token"},
        )
        assert resp.status_code == 200

    def test_search_unauthenticated_returns_401(self, auth_client):
        resp = auth_client.get("/api/knowledge/search", params={"q": "test"})
        assert resp.status_code == 401

    def test_search_valid_token_returns_200(self, auth_client):
        resp = auth_client.get(
            "/api/knowledge/search",
            params={"q": "test"},
            headers={"Authorization": "Bearer valid-jwt-token"},
        )
        assert resp.status_code == 200

    def test_entries_unauthenticated_returns_401(self, auth_client):
        resp = auth_client.post(
            "/api/knowledge/entries",
            json={"title": "Test", "content": "Content"},
        )
        assert resp.status_code == 401

    def test_entries_valid_token_returns_201(self, auth_client):
        resp = auth_client.post(
            "/api/knowledge/entries",
            json={"title": "Test", "content": "Content"},
            headers={"Authorization": "Bearer valid-jwt-token"},
        )
        assert resp.status_code == 201

    def test_decisions_unauthenticated_returns_401(self, auth_client):
        resp = auth_client.post(
            "/api/knowledge/decisions",
            json={
                "title": "T",
                "decision": "D",
                "reasoning": "R",
                "alternatives": [],
                "context": "C",
            },
        )
        assert resp.status_code == 401

    def test_decisions_valid_token_returns_201(self, auth_client):
        resp = auth_client.post(
            "/api/knowledge/decisions",
            json={
                "title": "T",
                "decision": "D",
                "reasoning": "R",
                "alternatives": [],
                "context": "C",
            },
            headers={"Authorization": "Bearer valid-jwt-token"},
        )
        assert resp.status_code == 201


class TestServiceAccountJWT:
    """Service accounts with JWT tokens (role=service_role) are allowed."""

    def test_service_jwt_can_notify(self, auth_client):
        resp = auth_client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer service-jwt-token"},
        )
        assert resp.status_code == 200

    def test_service_jwt_can_search(self, auth_client):
        resp = auth_client.get(
            "/api/knowledge/search",
            params={"q": "test"},
            headers={"Authorization": "Bearer service-jwt-token"},
        )
        assert resp.status_code == 200

    def test_service_jwt_can_create_entry(self, auth_client):
        resp = auth_client.post(
            "/api/knowledge/entries",
            json={
                "title": "Planner Entry",
                "content": "Created by planner.",
                "source": "bsnexus-planner",
            },
            headers={"Authorization": "Bearer service-jwt-token"},
        )
        assert resp.status_code == 201

    def test_service_jwt_can_create_decision(self, auth_client):
        resp = auth_client.post(
            "/api/knowledge/decisions",
            json={
                "title": "D",
                "decision": "D",
                "reasoning": "R",
                "alternatives": [],
                "context": "C",
                "source": "bsnexus-planner",
            },
            headers={"Authorization": "Bearer service-jwt-token"},
        )
        assert resp.status_code == 201


class TestServiceAPIKey:
    """Service-to-service calls via X-Service-Key header."""

    def test_valid_service_key_grants_access(self, service_key_client):
        resp = service_key_client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"X-Service-Key": "secret-service-key-123"},
        )
        assert resp.status_code == 200

    def test_service_key_can_search(self, service_key_client):
        resp = service_key_client.get(
            "/api/knowledge/search",
            params={"q": "test"},
            headers={"X-Service-Key": "secret-service-key-123"},
        )
        assert resp.status_code == 200

    def test_service_key_can_create_entry(self, service_key_client):
        resp = service_key_client.post(
            "/api/knowledge/entries",
            json={
                "title": "Planner Entry",
                "content": "Created by planner.",
                "source": "bsnexus-planner",
            },
            headers={"X-Service-Key": "secret-service-key-123"},
        )
        assert resp.status_code == 201

    def test_service_key_can_create_decision(self, service_key_client):
        resp = service_key_client.post(
            "/api/knowledge/decisions",
            json={
                "title": "D",
                "decision": "D",
                "reasoning": "R",
                "alternatives": [],
                "context": "C",
                "source": "bsnexus-planner",
            },
            headers={"X-Service-Key": "secret-service-key-123"},
        )
        assert resp.status_code == 201

    def test_invalid_service_key_returns_401(self, service_key_client):
        resp = service_key_client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"X-Service-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_no_credentials_returns_401(self, service_key_client):
        """Neither Bearer nor X-Service-Key provided."""
        resp = service_key_client.post("/api/notify", json={"message": "test"})
        assert resp.status_code == 401


class TestAuthDisabled:
    """When auth is disabled, anonymous access works."""

    def test_notify_accessible(self, open_client):
        resp = open_client.post("/api/notify", json={"message": "test"})
        assert resp.status_code == 200

    def test_search_accessible(self, open_client):
        resp = open_client.get("/api/knowledge/search", params={"q": "test"})
        assert resp.status_code == 200


class TestPublicEndpoints:
    """Public endpoints remain accessible even with auth enabled."""

    def test_health_no_auth_required(self, auth_client):
        resp = auth_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
