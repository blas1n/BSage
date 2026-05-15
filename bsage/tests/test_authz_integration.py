"""bsvibe-authz integration tests for the BSage Gateway.

Verifies that knowledge / vault / decisions / notify endpoints route through
the shared ``bsvibe_authz`` library deps:

- ``state.get_current_user`` is ``combined_principal("bsage")`` — accepts a
  user JWT *or* an ``aud=bsage`` service JWT on the same path.
- read routes use ``require_permission`` — permissive (any authenticated
  caller passes) while ``settings.openfga_api_url`` is empty; once it is set
  the OpenFGA ``check`` is enforced and a negative response → 403.
- write / execute / draft routes use ``require_admin`` — role-gated:
  ``owner``/``admin`` JWT roles and service principals pass, anything else
  403s. This is enforced even with no OpenFGA deployed.

Authentication routing matrix (BSage):

| Route                              | Auth principal           | Guard                |
|------------------------------------|--------------------------|----------------------|
| GET  /api/knowledge/search         | user OR service          | require_permission   |
| POST /api/knowledge/entries        | admin user OR service    | require_admin        |
| POST /api/knowledge/decisions      | admin user OR service    | require_admin        |
| GET  /api/knowledge/catalog        | user OR service          | require_permission   |
| GET  /api/vault/file               | user OR service          | require_permission   |
| GET  /api/vault/tree               | user OR service          | require_permission   |
| GET  /api/vault/search             | user OR service          | require_permission   |
| POST /api/notify                   | admin user OR service    | require_admin        |

bsage-sync.sh consumes ``/api/knowledge/{entries,decisions,search}`` and
``/api/vault/file`` with an admin user JWT — those flows must keep working.
BSNexus knowledge_client.py uses a service JWT (aud=bsage) for the same
routes — the dual-acceptance test confirms both succeed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from bsvibe_authz import (
    FGAClientProtocol,
    OpenFGAError,
    PermissionCache,
    User,
    get_openfga_client,
    get_permission_cache,
    get_settings_dep,
)
from bsvibe_authz.settings import Settings as AuthzSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.ontology import OntologyRegistry
from bsage.garden.sync import SyncManager
from bsage.garden.vault import Vault
from bsage.garden.writer_core import GardenWriter
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes

# ---------------------------------------------------------------------------
# Test doubles for bsvibe-authz dependencies
# ---------------------------------------------------------------------------


class _AlwaysAllowFGA:
    """OpenFGA stub that grants every check."""

    async def check(self, user: str, relation: str, object_: str) -> bool:
        return True

    async def list_objects(self, user: str, relation: str, type_: str) -> list[str]:
        return []

    async def write_tuple(self, user: str, relation: str, object_: str) -> None:
        # bsvibe-authz 1.3.0 lazy auto-provision write. No-op for tests.
        return None


class _DenyFGA:
    """OpenFGA stub that denies every check — used to assert 403 wiring."""

    async def check(self, user: str, relation: str, object_: str) -> bool:
        return False

    async def list_objects(self, user: str, relation: str, type_: str) -> list[str]:
        return []

    async def write_tuple(self, user: str, relation: str, object_: str) -> None:
        return None


class _ErrorFGA:
    async def check(self, user: str, relation: str, object_: str) -> bool:
        raise OpenFGAError(400, {"code": "validation_error", "message": "bad relation"})

    async def list_objects(self, user: str, relation: str, type_: str) -> list[str]:
        return []

    async def write_tuple(self, user: str, relation: str, object_: str) -> None:
        return None


def _permissive_settings() -> AuthzSettings:
    """Settings with an empty ``openfga_api_url`` — require_permission is
    permissive (authenticated callers pass without an FGA check)."""
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


def _openfga_settings() -> AuthzSettings:
    """Settings with a non-empty ``openfga_api_url`` — require_permission
    enforces the OpenFGA ``check``."""
    return AuthzSettings(
        bsvibe_auth_url="https://auth.bsvibe.dev",
        openfga_api_url="http://openfga.test:8080",
        openfga_store_id="test-store",
        openfga_auth_model_id="test-model",
        service_token_signing_secret="test-service-secret",  # noqa: S106
        user_jwt_secret="test-user-secret",  # noqa: S106
        user_jwt_audience="bsvibe",
        user_jwt_issuer="https://auth.bsvibe.dev",
    )


def _user_principal(
    *,
    user_id: str = "user-1",
    email: str = "admin@bsvibe.dev",
    tenant_id: str = "tenant-default",
    admin: bool = True,
) -> User:
    """Build a User the way ``parse_user_token`` would.

    ``admin=True`` lifts ``app_metadata.role='admin'`` so the principal
    passes ``require_admin``-gated write routes (bsage-sync.sh runs with an
    admin user JWT).
    """
    return User(
        id=user_id,
        email=email,
        active_tenant_id=tenant_id,
        tenants=[],
        is_service=False,
        app_metadata={"role": "admin"} if admin else {},
    )


def _service_principal(
    *,
    sub: str = "service:bsnexus",
    tenant_id: str = "tenant-default",
) -> User:
    """Service principal as ``combined_principal('bsage')`` resolves it from
    a verified ``aud=bsage`` service JWT."""
    return User(
        id=sub,
        email=None,
        active_tenant_id=tenant_id,
        tenants=[],
        is_service=True,
    )


# ---------------------------------------------------------------------------
# State fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    Vault(root).ensure_dirs()
    return root


@pytest.fixture()
def real_state(vault_root: Path):
    """AppState with real GardenWriter + Vault + Ontology so that route handlers
    that read from disk work end-to-end. Auth is wired through bsvibe-authz."""
    import asyncio

    vault = Vault(vault_root)
    sync_manager = SyncManager()
    ontology = OntologyRegistry(vault_root / ".bsage" / "ontology.yaml")
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(ontology.load())
    finally:
        loop.close()
    writer = GardenWriter(vault=vault, sync_manager=sync_manager, ontology=ontology)

    state = MagicMock(spec=AppState)
    state.skill_loader = MagicMock()
    state.skill_loader.load_all = AsyncMock(return_value={})
    state.plugin_loader = MagicMock()
    state.plugin_loader.load_all = AsyncMock(return_value={})
    state.agent_loop = MagicMock()
    state.vault = vault
    state.runtime_config = RuntimeConfig(
        llm_model="anthropic/claude-sonnet-4-20250514",
        llm_api_key="test-key",
        llm_api_base=None,
        safe_mode=True,
        disabled_entries=[],
    )
    state.sync_manager = sync_manager
    state.danger_map = {}
    state.credential_store = MagicMock()
    state.credential_store.list_services = MagicMock(return_value=[])
    state.retriever = MagicMock()
    state.retriever.index_available = False
    state.embedder = MagicMock()
    state.embedder.enabled = False
    state.vector_store = None
    state.prompt_registry = MagicMock(spec=PromptRegistry)
    state.prompt_registry.get = MagicMock(return_value="prompt")
    state.prompt_registry.render = MagicMock(return_value="prompt")
    state.chat_bridge = AsyncMock()
    state.garden_writer = writer
    state.ontology = ontology
    state.auth_provider = None  # legacy field, kept for back-compat
    state.tenant_id = "tenant-default"

    # Default no-op principal so create_routes can wire its dep tree without
    # the per-test fixture having to set it. Tests that exercise auth
    # override this via _build_app.
    async def _default_principal():
        raise RuntimeError("no principal configured for this test")

    state.get_current_user = _default_principal

    return state


def _build_app(
    state,
    *,
    user: User | None = None,
    service: User | None = None,
    fga: FGAClientProtocol | None = None,
    settings: AuthzSettings | None = None,
) -> FastAPI:
    """Create a FastAPI app where the bsvibe-authz dependency tree is wired to
    return the given principal / FGA stub. Either ``user`` xor ``service`` is
    provided per request scope.

    The fixture stamps ``state.get_current_user`` with a coroutine returning
    the chosen principal so that:
      1. The router-level auth dep (``Depends(state.get_current_user)``) accepts.
      2. ``require_permission`` / ``require_admin`` (wired by the route factory
         with ``principal_dep=state.get_current_user``) see the same principal.
    OpenFGA + permission cache + settings are overridden via
    ``app.dependency_overrides`` of the shared library deps.

    ``settings`` defaults to ``_permissive_settings()`` (empty openfga_api_url)
    so read routes pass for any authenticated caller. Pass
    ``_openfga_settings()`` + an FGA stub to exercise the enforced path.
    """
    fga = fga or _AlwaysAllowFGA()
    settings = settings or _permissive_settings()
    cache = PermissionCache(ttl_s=30)

    principal = user if user is not None else service

    if principal is not None:

        async def _principal():
            return principal

    else:

        async def _principal():
            raise RuntimeError("no principal configured for this test")

    state.get_current_user = _principal

    app = FastAPI()
    app.include_router(create_routes(state))

    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_openfga_client] = lambda: fga
    app.dependency_overrides[get_permission_cache] = lambda: cache

    return app


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestUserJwtAccess:
    """Admin user JWT (admin@bsvibe.dev via bsage-sync.sh) reaches every sync route."""

    def test_search_with_user_jwt_returns_200(self, real_state) -> None:
        app = _build_app(real_state, user=_user_principal())
        client = TestClient(app)
        resp = client.get(
            "/api/knowledge/search",
            params={"q": "anything"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 200, resp.text

    def test_create_entry_with_user_jwt_returns_201(self, real_state) -> None:
        app = _build_app(real_state, user=_user_principal())
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "T", "content": "C", "source": "test"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 201, resp.text

    def test_create_decision_with_user_jwt_returns_201(self, real_state) -> None:
        app = _build_app(real_state, user=_user_principal())
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/decisions",
            json={"title": "Q", "decision": "D", "reasoning": "R"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 201, resp.text

    def test_vault_file_with_user_jwt_returns_200(self, real_state, vault_root: Path) -> None:
        # Seed a vault file
        (vault_root / "ideas").mkdir(exist_ok=True)
        (vault_root / "ideas" / "test.md").write_text(
            "---\ntenant_id: tenant-default\n---\n# Test\n",
            encoding="utf-8",
        )

        app = _build_app(real_state, user=_user_principal())
        client = TestClient(app)
        resp = client.get(
            "/api/vault/file",
            params={"path": "ideas/test.md"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 200, resp.text


class TestServiceJwtAccess:
    """Service JWT with audience=bsage (BSNexus → BSage) reaches every route
    BSNexus knowledge_client.py uses. ``require_admin`` lets verified service
    principals through the write routes."""

    def test_search_with_service_jwt_returns_200(self, real_state) -> None:
        app = _build_app(real_state, service=_service_principal())
        client = TestClient(app)
        resp = client.get(
            "/api/knowledge/search",
            params={"q": "anything"},
            headers={"Authorization": "Bearer fake-service-token"},
        )
        assert resp.status_code == 200, resp.text

    def test_create_entry_with_service_jwt_returns_201(self, real_state) -> None:
        app = _build_app(real_state, service=_service_principal())
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "Planner", "content": "C", "source": "bsnexus-planner"},
            headers={"Authorization": "Bearer fake-service-token"},
        )
        assert resp.status_code == 201, resp.text

    def test_create_decision_with_service_jwt_returns_201(self, real_state) -> None:
        app = _build_app(real_state, service=_service_principal())
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/decisions",
            json={"title": "Q", "decision": "D", "reasoning": "R"},
            headers={"Authorization": "Bearer fake-service-token"},
        )
        assert resp.status_code == 201, resp.text


class TestNoCredentialsRejected:
    """No Bearer header → 401 from combined_principal('bsage')."""

    def test_search_without_auth_returns_401(self, real_state) -> None:
        """The real library ``combined_principal('bsage')`` must reject calls
        without an Authorization header. ``real_state.get_current_user`` is
        already that dep (set in dependencies.AppState.__init__)."""
        from bsvibe_authz import combined_principal

        real_state.get_current_user = combined_principal("bsage")

        app = FastAPI()
        app.include_router(create_routes(real_state))
        app.dependency_overrides[get_settings_dep] = _permissive_settings
        app.dependency_overrides[get_openfga_client] = lambda: _AlwaysAllowFGA()
        app.dependency_overrides[get_permission_cache] = lambda: PermissionCache(30)

        client = TestClient(app)
        resp = client.get("/api/knowledge/search", params={"q": "x"})
        assert resp.status_code == 401

    def test_health_remains_public(self, real_state) -> None:
        """/api/health must not require auth."""
        app = FastAPI()
        app.include_router(create_routes(real_state))
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200


class TestRequirePermissionEnforced:
    """With a non-empty openfga_api_url, read routes enforce the OpenFGA
    ``check`` — a negative response → 403, errors do not escape as 500."""

    def test_search_denies_when_fga_says_no(self, real_state) -> None:
        app = _build_app(
            real_state,
            user=_user_principal(),
            fga=_DenyFGA(),
            settings=_openfga_settings(),
        )
        client = TestClient(app)
        resp = client.get(
            "/api/knowledge/search",
            params={"q": "x"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 403

    def test_search_passes_when_fga_says_yes(self, real_state) -> None:
        app = _build_app(
            real_state,
            user=_user_principal(),
            fga=_AlwaysAllowFGA(),
            settings=_openfga_settings(),
        )
        client = TestClient(app)
        resp = client.get(
            "/api/knowledge/search",
            params={"q": "x"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 200, resp.text

    def test_openfga_errors_propagate_not_swallowed(self, real_state) -> None:
        # An OpenFGAError from the client bubbles out of require_permission —
        # FastAPI turns the unhandled exception into a 500. The point of this
        # test is that the error is not silently treated as "allowed".
        app = _build_app(
            real_state,
            user=_user_principal(),
            fga=_ErrorFGA(),
            settings=_openfga_settings(),
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/knowledge/search",
            params={"q": "x"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code != 200


class TestRequireAdminEnforced:
    """Write / execute routes use ``require_admin`` — role-gated, enforced
    even with no OpenFGA deployed."""

    def test_non_admin_user_denied_on_write_route(self, real_state) -> None:
        app = _build_app(real_state, user=_user_principal(admin=False))
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "T", "content": "C", "source": "test"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 403

    def test_admin_user_allowed_on_write_route(self, real_state) -> None:
        app = _build_app(real_state, user=_user_principal(admin=True))
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "T", "content": "C", "source": "test"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 201, resp.text

    def test_service_principal_allowed_on_write_route(self, real_state) -> None:
        app = _build_app(real_state, service=_service_principal())
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "Svc", "content": "C", "source": "bsnexus"},
            headers={"Authorization": "Bearer fake-service-token"},
        )
        assert resp.status_code == 201, resp.text

    def test_non_admin_user_denied_on_run_route(self, real_state) -> None:
        real_state.agent_loop.get_entry = MagicMock(return_value=object())
        real_state.agent_loop.run_entry_direct = AsyncMock(return_value={"ok": True})

        app = _build_app(real_state, user=_user_principal(admin=False))
        client = TestClient(app)
        resp = client.post(
            "/api/run/garden-writer",
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 403

    def test_admin_user_allowed_on_run_route(self, real_state) -> None:
        real_state.agent_loop.get_entry = MagicMock(return_value=object())
        real_state.agent_loop.run_entry_direct = AsyncMock(return_value={"ok": True})

        app = _build_app(real_state, user=_user_principal(admin=True))
        client = TestClient(app)
        resp = client.post(
            "/api/run/garden-writer",
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 200, resp.text


class TestTenantIsolation:
    """Notes written through the API must carry the caller's active_tenant_id
    in their frontmatter, so that retrieval can filter by tenant."""

    def test_entry_persists_tenant_id_in_frontmatter(self, real_state, vault_root: Path) -> None:
        app = _build_app(real_state, user=_user_principal(tenant_id="tenant-alice"))
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "TenantTest", "content": "Body", "source": "test"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 201, resp.text
        rel_path = resp.json()["path"]
        text = (vault_root / rel_path).read_text(encoding="utf-8")
        assert "tenant_id: tenant-alice" in text

    def test_decision_persists_tenant_id_in_frontmatter(self, real_state, vault_root: Path) -> None:
        app = _build_app(real_state, user=_user_principal(tenant_id="tenant-alice"))
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/decisions",
            json={"title": "Q", "decision": "D", "reasoning": "R"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 201, resp.text
        rel_path = resp.json()["path"]
        text = (vault_root / rel_path).read_text(encoding="utf-8")
        assert "tenant_id: tenant-alice" in text

    def test_service_call_persists_tenant_id_from_token(self, real_state, vault_root: Path) -> None:
        app = _build_app(
            real_state,
            service=_service_principal(tenant_id="tenant-bob"),
        )
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "ServiceWrite", "content": "Body", "source": "bsnexus"},
            headers={"Authorization": "Bearer fake-service-token"},
        )
        assert resp.status_code == 201, resp.text
        rel_path = resp.json()["path"]
        text = (vault_root / rel_path).read_text(encoding="utf-8")
        assert "tenant_id: tenant-bob" in text

    def test_vault_search_hides_other_tenant_notes(self, real_state, vault_root: Path) -> None:
        (vault_root / "ideas").mkdir(exist_ok=True)
        (vault_root / "ideas" / "mine.md").write_text(
            "---\ntenant_id: tenant-alice\n---\nalpha visible marker\n",
            encoding="utf-8",
        )
        (vault_root / "ideas" / "theirs.md").write_text(
            "---\ntenant_id: tenant-bob\n---\nalpha secret marker\n",
            encoding="utf-8",
        )

        app = _build_app(real_state, user=_user_principal(tenant_id="tenant-alice"))
        client = TestClient(app)
        resp = client.get(
            "/api/vault/search",
            params={"q": "alpha"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 200, resp.text
        paths = {item["path"] for item in resp.json()}
        assert "ideas/mine.md" in paths
        assert "ideas/theirs.md" not in paths

    def test_vault_file_hides_other_tenant_notes(self, real_state, vault_root: Path) -> None:
        (vault_root / "ideas").mkdir(exist_ok=True)
        (vault_root / "ideas" / "theirs.md").write_text(
            "---\ntenant_id: tenant-bob\n---\nsecret body\n",
            encoding="utf-8",
        )

        app = _build_app(real_state, user=_user_principal(tenant_id="tenant-alice"))
        client = TestClient(app)
        resp = client.get(
            "/api/vault/file",
            params={"path": "ideas/theirs.md"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 404


class TestSyncApiContractStillHolds:
    """bsage-sync.sh must keep working after the authz library migration.
    Smoke-test the wire shape under the new auth."""

    def test_entries_response_keys_unchanged(self, real_state) -> None:
        app = _build_app(real_state, user=_user_principal())
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "T", "content": "C", "source": "test"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert set(body.keys()) == {"id", "path", "created_at"}

    def test_search_response_top_level_unchanged(self, real_state) -> None:
        app = _build_app(real_state, user=_user_principal())
        client = TestClient(app)
        resp = client.get(
            "/api/knowledge/search",
            params={"q": "anything"},
            headers={"Authorization": "Bearer fake-user-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"results"}
        assert isinstance(body["results"], list)
