"""TASK-005 — token-cutover smoke for MCP endpoints.

End-to-end via TestClient: the real ``create_mcp_routes`` router is mounted
with ``state.get_current_user = combined_principal`` so the full 4-way
dispatch (service JWT / bootstrap / opaque / user JWT) flows through to a
real MCP handler. Introspection is faked via FastAPI dep overrides — no
network. The companion ``/scoped_invoke`` route layers ``require_scope``
on top of the same principal source so the ``sage:mcp:invoke`` enforcement
path is also covered.

Cases:
    (a) ``Bearer bsv_admin_<secret>`` → 200 (admin scope=['*']).
    (b) ``Bearer bsv_sk_<id>`` w/ introspect scope=['sage:mcp:invoke']
        → 200; same shape with empty scope → 403 on scoped route.
    (c) Service JWT (Phase 0 P0.5 invariant) → 200.
    (d) Invalid / missing token → 401.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from bsvibe_authz import IntrospectionResponse, User
from bsvibe_authz.cache import IntrospectionCache
from bsvibe_authz.deps import _scope_grants
from bsvibe_authz.settings import Settings as AuthzSettings
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from bsage.core.runtime_config import RuntimeConfig
from bsage.gateway.authz import (
    _get_introspection_cache_dep,
    _get_introspection_client_dep,
    _settings_dep,
    combined_principal,
)
from bsage.gateway.dependencies import AppState
from bsage.gateway.mcp import create_mcp_routes
from bsage.tests.conftest import make_plugin_meta, make_skill_meta

_USER_JWT_SECRET = "test-user-secret"  # noqa: S105
_SERVICE_TOKEN_SECRET = "test-service-secret"  # noqa: S105
_BOOTSTRAP_TOKEN = "bsv_admin_cutover_smoke_secret"  # noqa: S105
_BOOTSTRAP_HASH = hashlib.sha256(_BOOTSTRAP_TOKEN.encode()).hexdigest()


def _build_settings() -> AuthzSettings:
    return AuthzSettings(
        bsvibe_auth_url="https://auth.bsvibe.dev",
        openfga_api_url="",  # permissive — no FGA in smoke
        openfga_store_id="",
        openfga_auth_model_id="",
        service_token_signing_secret=_SERVICE_TOKEN_SECRET,
        user_jwt_secret=_USER_JWT_SECRET,
        user_jwt_audience="bsvibe",
        user_jwt_issuer="https://auth.bsvibe.dev",
        bootstrap_token_hash=_BOOTSTRAP_HASH,
        introspection_url="https://auth.bsvibe.dev/oauth/introspect",
        introspection_client_id="bsage",
        introspection_client_secret="introspect-secret",  # noqa: S106
    )


@pytest.fixture()
def mock_state() -> MagicMock:
    """Mocked AppState with ``get_current_user`` wired to combined_principal."""
    state = MagicMock(spec=AppState)
    state.get_current_user = combined_principal

    state.plugin_loader = MagicMock()
    state.plugin_loader.load_all = AsyncMock(
        return_value={"my-plugin": make_plugin_meta(name="my-plugin", category="input")}
    )
    state.skill_loader = MagicMock()
    state.skill_loader.load_all = AsyncMock(
        return_value={"my-skill": make_skill_meta(name="my-skill")}
    )

    state.runtime_config = RuntimeConfig(
        llm_model="test-model",
        llm_api_key="test-key",
        llm_api_base=None,
        safe_mode=True,
        disabled_entries=[],
    )
    state.credential_store = MagicMock()
    state.credential_store.list_services = MagicMock(return_value=[])
    return state


@pytest.fixture()
def app_factory(mock_state: MagicMock) -> Callable[..., FastAPI]:
    """Build an app mounting the real MCP router + a scope-protected route."""

    def _build(introspection_response: IntrospectionResponse | None = None) -> FastAPI:
        app = FastAPI()
        app.include_router(create_mcp_routes(mock_state))

        # Scope-protected smoke endpoint — re-uses combined_principal so
        # introspection-resolved scopes flow through unchanged.
        async def _require_invoke_scope(
            user: User = Depends(combined_principal),
        ) -> None:
            if not _scope_grants(user.scope, "sage:mcp:invoke"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="missing required scope: sage:mcp:invoke",
                )

        @app.get("/api/mcp/scoped_invoke", dependencies=[Depends(_require_invoke_scope)])
        async def _scoped_invoke() -> dict:
            return {"ok": True}

        settings = _build_settings()
        app.dependency_overrides[_settings_dep] = lambda: settings

        if introspection_response is not None:
            mock_client = AsyncMock()
            mock_client.introspect = AsyncMock(return_value=introspection_response)
            app.dependency_overrides[_get_introspection_client_dep] = lambda: mock_client
        else:
            app.dependency_overrides[_get_introspection_client_dep] = lambda: None

        cache = IntrospectionCache(ttl_s=30)
        app.dependency_overrides[_get_introspection_cache_dep] = lambda: cache
        return app

    return _build


# ---------------------------------------------------------------------------
# (a) Bootstrap admin
# ---------------------------------------------------------------------------
class TestBootstrapAdmin:
    def test_list_plugins_with_bootstrap_token_returns_200(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        client = TestClient(app_factory())
        resp = client.get(
            "/api/mcp/list_plugins",
            headers={"Authorization": f"Bearer {_BOOTSTRAP_TOKEN}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2

    def test_scoped_invoke_with_bootstrap_token_returns_200(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        # Admin scope=['*'] satisfies any required scope.
        client = TestClient(app_factory())
        resp = client.get(
            "/api/mcp/scoped_invoke",
            headers={"Authorization": f"Bearer {_BOOTSTRAP_TOKEN}"},
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# (b) Opaque session token (RFC 7662 introspection)
# ---------------------------------------------------------------------------
class TestOpaqueSessionToken:
    def test_active_opaque_with_invoke_scope_passes_scoped_route(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        response = IntrospectionResponse(
            active=True,
            sub="user-7",
            tenant="tenant-7",
            scope=["sage:mcp:invoke"],
        )
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/api/mcp/scoped_invoke",
            headers={"Authorization": "Bearer bsv_sk_active"},
        )
        assert resp.status_code == 200, resp.text

    def test_active_opaque_with_invoke_scope_passes_list_plugins(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        response = IntrospectionResponse(
            active=True,
            sub="user-7",
            tenant="tenant-7",
            scope=["sage:mcp:invoke"],
        )
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/api/mcp/list_plugins",
            headers={"Authorization": "Bearer bsv_sk_active"},
        )
        assert resp.status_code == 200, resp.text

    def test_active_opaque_without_invoke_scope_returns_403(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        # Token is active (auth OK) but lacks the required scope.
        response = IntrospectionResponse(
            active=True,
            sub="user-7",
            tenant="tenant-7",
            scope=["sage:read"],
        )
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/api/mcp/scoped_invoke",
            headers={"Authorization": "Bearer bsv_sk_no_scope"},
        )
        assert resp.status_code == 403
        assert "sage:mcp:invoke" in resp.json()["detail"]

    def test_inactive_opaque_returns_401(self, app_factory: Callable[..., FastAPI]) -> None:
        response = IntrospectionResponse(active=False)
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/api/mcp/list_plugins",
            headers={"Authorization": "Bearer bsv_sk_revoked"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# (c) Service JWT (Phase 0 P0.5 invariant)
# ---------------------------------------------------------------------------
class TestServiceJwt:
    def test_service_jwt_passes_mcp_route(self, app_factory: Callable[..., FastAPI]) -> None:
        token = jwt.encode(
            {
                "sub": "service:bsnexus",
                "aud": "sage",
                "iss": "https://auth.bsvibe.dev",
                "iat": 1700000000,
                "exp": 1900000000,
                "scope": "sage:read",
                "token_type": "service",
                "tenant_id": "tenant-default",
            },
            _SERVICE_TOKEN_SECRET,
            algorithm="HS256",
        )
        client = TestClient(app_factory())
        resp = client.get(
            "/api/mcp/list_plugins",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# (d) Invalid / missing token
# ---------------------------------------------------------------------------
class TestInvalidToken:
    def test_missing_authorization_returns_401(self, app_factory: Callable[..., FastAPI]) -> None:
        client = TestClient(app_factory())
        resp = client.get("/api/mcp/list_plugins")
        assert resp.status_code == 401

    def test_garbage_bearer_returns_401(self, app_factory: Callable[..., FastAPI]) -> None:
        client = TestClient(app_factory())
        resp = client.get(
            "/api/mcp/list_plugins",
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        assert resp.status_code == 401
