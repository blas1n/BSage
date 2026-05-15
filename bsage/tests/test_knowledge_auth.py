"""Auth enforcement on /api/knowledge/* + /api/notify endpoints.

Migrated to the shared ``bsvibe_authz`` library deps:

- ``state.get_current_user`` is ``combined_principal("bsage")`` — a missing
  / invalid Bearer token → 401.
- read routes (``/api/knowledge/search``) use ``require_permission`` —
  permissive: any authenticated caller passes while ``openfga_api_url`` is
  empty.
- write routes (``/api/knowledge/entries``, ``/decisions``, ``/api/notify``)
  use ``require_admin`` — only ``owner``/``admin`` JWT roles and service
  principals pass; a plain authenticated user 403s.

The legacy ``X-Service-Key`` header path is gone — service-to-service auth
now rides on an ``aud=bsage`` service JWT resolved by ``combined_principal``.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from bsvibe_authz import (
    PermissionCache,
    User,
    combined_principal,
    get_openfga_client,
    get_permission_cache,
    get_settings_dep,
)
from bsvibe_authz.settings import Settings as AuthzSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.sync import SyncManager
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes


class _AllowFGA:
    async def check(self, user: str, relation: str, object_: str) -> bool:
        return True

    async def list_objects(self, user: str, relation: str, type_: str) -> list[str]:
        return []

    async def write_tuple(self, user: str, relation: str, object_: str) -> None:
        # bsvibe-authz 1.3.0 lazy auto-provision write. No-op for tests.
        return None


def _authz_settings() -> AuthzSettings:
    """Permissive — empty openfga_api_url, so require_permission passes any
    authenticated caller."""
    return AuthzSettings(
        bsvibe_auth_url="https://auth.bsvibe.dev",
        openfga_api_url="",
        openfga_store_id="",
        openfga_auth_model_id="",
        service_token_signing_secret="test-service-secret",  # noqa: S106
        user_jwt_secret="test-user-secret",  # noqa: S106
        user_jwt_audience="bsvibe",
        user_jwt_issuer="https://auth.bsvibe.dev",
    )


def _admin_user() -> User:
    return User(
        id="user-1",
        email="admin@test.com",
        active_tenant_id="tenant-default",
        tenants=[],
        is_service=False,
        app_metadata={"role": "admin"},
    )


def _plain_user() -> User:
    return User(
        id="user-2",
        email="user@test.com",
        active_tenant_id="tenant-default",
        tenants=[],
        is_service=False,
        app_metadata={},
    )


def _service_user() -> User:
    return User(
        id="service:bsnexus",
        email=None,
        active_tenant_id="tenant-default",
        tenants=[],
        is_service=True,
    )


def _build_vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "vault"
    facts_dir = vault_root / "facts"
    facts_dir.mkdir(parents=True)
    (facts_dir / "test-fact.md").write_text(
        "---\ntype: fact\nstatus: seed\ntags:\n  - test\n"
        "captured_at: '2026-03-01'\n---\n# Test Fact\n\nTest content.\n"
    )
    return vault_root


def _make_state(vault_root: Path) -> MagicMock:
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

    ontology = MagicMock()
    ontology.get_entity_types.return_value = {
        "idea": {"folder": "ideas/", "knowledge_layer": "semantic"},
        "insight": {"folder": "insights/", "knowledge_layer": "semantic"},
        "fact": {"folder": "facts/", "knowledge_layer": "semantic"},
        "task": {"folder": "tasks/", "knowledge_layer": "episodic"},
    }
    state.ontology = ontology

    state.auth_provider = None
    # Default: the real library dep — exercises the 401 path. Per-test
    # helpers below override it with a fixed principal.
    state.get_current_user = combined_principal("bsage")
    return state


def _app_for(state: MagicMock, principal: User | None = None) -> FastAPI:
    """Build an app. When ``principal`` is given, override
    ``state.get_current_user`` to return it; otherwise leave the real
    ``combined_principal('bsage')`` dep in place (so missing/invalid tokens
    401 as in production)."""
    if principal is not None:

        async def _principal() -> User:
            return principal

        state.get_current_user = _principal

    app = FastAPI()
    app.include_router(create_routes(state))
    app.dependency_overrides[get_settings_dep] = _authz_settings
    app.dependency_overrides[get_openfga_client] = lambda: _AllowFGA()
    app.dependency_overrides[get_permission_cache] = lambda: PermissionCache(30)
    return app


@pytest.fixture()
def vault_root(tmp_path):
    return _build_vault(tmp_path)


@pytest.fixture()
def state(vault_root):
    return _make_state(vault_root)


class TestUnauthenticatedRejected:
    """No / invalid Bearer token → 401 from combined_principal('bsage')."""

    def test_notify_unauthenticated_returns_401(self, state):
        client = TestClient(_app_for(state))
        resp = client.post("/api/notify", json={"message": "test"})
        assert resp.status_code == 401

    def test_notify_invalid_token_returns_401(self, state):
        client = TestClient(_app_for(state))
        resp = client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401

    def test_search_unauthenticated_returns_401(self, state):
        client = TestClient(_app_for(state))
        resp = client.get("/api/knowledge/search", params={"q": "test"})
        assert resp.status_code == 401

    def test_entries_unauthenticated_returns_401(self, state):
        client = TestClient(_app_for(state))
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "Test", "content": "Content"},
        )
        assert resp.status_code == 401


class TestReadRoutesPermissive:
    """Read routes use require_permission — any authenticated user passes
    while OpenFGA is not deployed (empty openfga_api_url)."""

    def test_plain_user_can_search(self, state):
        client = TestClient(_app_for(state, _plain_user()))
        resp = client.get(
            "/api/knowledge/search",
            params={"q": "test"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 200, resp.text

    def test_admin_user_can_search(self, state):
        client = TestClient(_app_for(state, _admin_user()))
        resp = client.get(
            "/api/knowledge/search",
            params={"q": "test"},
            headers={"Authorization": "Bearer fake-admin-token"},
        )
        assert resp.status_code == 200, resp.text


class TestWriteRoutesRequireAdmin:
    """Write routes use require_admin — plain users 403, admins + service
    principals pass."""

    def test_plain_user_denied_notify(self, state):
        client = TestClient(_app_for(state, _plain_user()))
        resp = client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 403

    def test_plain_user_denied_create_entry(self, state):
        client = TestClient(_app_for(state, _plain_user()))
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "Test", "content": "Content"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 403

    def test_admin_user_can_notify(self, state):
        client = TestClient(_app_for(state, _admin_user()))
        resp = client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer fake-admin-token"},
        )
        assert resp.status_code == 200, resp.text

    def test_admin_user_can_create_entry(self, state):
        client = TestClient(_app_for(state, _admin_user()))
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "Test", "content": "Content"},
            headers={"Authorization": "Bearer fake-admin-token"},
        )
        assert resp.status_code == 201, resp.text

    def test_admin_user_can_create_decision(self, state):
        client = TestClient(_app_for(state, _admin_user()))
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "T",
                "decision": "D",
                "reasoning": "R",
                "alternatives": [],
                "context": "C",
            },
            headers={"Authorization": "Bearer fake-admin-token"},
        )
        assert resp.status_code == 201, resp.text


class TestServicePrincipalAccess:
    """An aud=bsage service principal (BSNexus → BSage) reaches both read and
    write routes — require_admin lets verified service callers through."""

    def test_service_can_search(self, state):
        client = TestClient(_app_for(state, _service_user()))
        resp = client.get(
            "/api/knowledge/search",
            params={"q": "test"},
            headers={"Authorization": "Bearer fake-service-token"},
        )
        assert resp.status_code == 200, resp.text

    def test_service_can_notify(self, state):
        client = TestClient(_app_for(state, _service_user()))
        resp = client.post(
            "/api/notify",
            json={"message": "test"},
            headers={"Authorization": "Bearer fake-service-token"},
        )
        assert resp.status_code == 200, resp.text

    def test_service_can_create_entry(self, state):
        client = TestClient(_app_for(state, _service_user()))
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "Planner Entry",
                "content": "Created by planner.",
                "source": "bsnexus-planner",
            },
            headers={"Authorization": "Bearer fake-service-token"},
        )
        assert resp.status_code == 201, resp.text

    def test_service_can_create_decision(self, state):
        client = TestClient(_app_for(state, _service_user()))
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "D",
                "decision": "D",
                "reasoning": "R",
                "alternatives": [],
                "context": "C",
                "source": "bsnexus-planner",
            },
            headers={"Authorization": "Bearer fake-service-token"},
        )
        assert resp.status_code == 201, resp.text


class TestPublicEndpoints:
    """Public endpoints remain accessible with no auth."""

    def test_health_no_auth_required(self, state):
        client = TestClient(_app_for(state))
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
