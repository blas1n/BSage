"""Token-cutover smoke for MCP endpoints.

End-to-end via TestClient: the real ``create_mcp_routes`` router is mounted
with ``state.get_current_user = combined_principal("bsage")`` so the full
dispatch (service JWT / PAT JWT via introspection / user JWT) flows through
to a real MCP handler. Introspection is faked via FastAPI dep overrides —
no network. The companion ``/scoped_invoke`` route layers ``require_scope``
on top of the same principal source so the ``bsage:mcp:invoke`` enforcement
path is also covered.

Note (Tier 2 cleanup, 2026-05): bsvibe-authz 1.3.0 removed the legacy
``bsv_sk_*`` opaque-prefix dispatch. Introspection is now reached ONLY via
the JWT-shaped fallback in ``get_current_user`` — a token must look like a
JWT (three base64url segments) AND fail ``verify_user_jwt`` (signed with a
different secret) before introspection is attempted. PAT JWTs from the
device-authorization grant are signed with ``SERVICE_TOKEN_SIGNING_SECRET``,
not ``USER_JWT_SECRET``, which is exactly that shape — so we forge that
shape in the tests below.

Cases:
    (a) PAT JWT (introspect-fallback) w/ scope=['bsage:mcp:invoke']
        → 200; same shape with empty scope → 403 on scoped route.
    (b) Service JWT (Phase 0 P0.5 invariant) → 200.
    (c) Invalid / missing token → 401.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from bsvibe_authz import (
    IntrospectionResponse,
    User,
    combined_principal,
    get_introspection_cache,
    get_introspection_client,
    get_settings_dep,
)
from bsvibe_authz.cache import IntrospectionCache
from bsvibe_authz.deps import _scope_grants
from bsvibe_authz.settings import Settings as AuthzSettings
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from bsage.core.runtime_config import RuntimeConfig
from bsage.gateway.dependencies import AppState
from bsage.gateway.mcp import create_mcp_routes
from bsage.tests.conftest import make_plugin_meta, make_skill_meta

_USER_JWT_SECRET = "test-user-secret"  # noqa: S105
_SERVICE_TOKEN_SECRET = "test-service-secret"  # noqa: S105
# PAT JWTs are minted by BSVibe-Auth's device-authorization grant; they're
# signed with a key the consumer service doesn't share, so they fail both
# ``verify_user_jwt`` and ``verify_service_jwt`` locally and only succeed via
# ``/oauth/introspect``. We forge "looks-like-a-PAT-JWT" by signing with a
# third secret that neither verifier knows.
_PAT_JWT_SECRET = "test-pat-unknown-secret"  # noqa: S105


def _make_pat_jwt(jti: str = "pat-active") -> str:
    """Build a JWT-shaped token that fails local verification.

    The payload contents do not matter for the introspection fallback —
    ``verify_via_introspection`` keys on the raw token, and the fake
    introspection client returns a fixed ``IntrospectionResponse``. The
    only requirement is that the string is shaped like a JWT
    (three base64url segments) so ``_looks_like_jwt`` returns True after
    ``verify_user_jwt`` raises ``AuthError``.
    """
    return jwt.encode(
        {
            "jti": jti,
            "iat": 1700000000,
            "exp": 1900000000,
        },
        _PAT_JWT_SECRET,
        algorithm="HS256",
    )


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
        introspection_url="https://auth.bsvibe.dev/oauth/introspect",
        introspection_client_id="bsage",
        introspection_client_secret="introspect-secret",  # noqa: S106
    )


@pytest.fixture()
def mock_state() -> MagicMock:
    """Mocked AppState with ``get_current_user`` wired to combined_principal."""
    state = MagicMock(spec=AppState)
    state.get_current_user = combined_principal("bsage")

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
            user: User = Depends(mock_state.get_current_user),
        ) -> None:
            if not _scope_grants(user.scope, "bsage:mcp:invoke"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="missing required scope: bsage:mcp:invoke",
                )

        @app.get("/api/mcp/scoped_invoke", dependencies=[Depends(_require_invoke_scope)])
        async def _scoped_invoke() -> dict:
            return {"ok": True}

        settings = _build_settings()
        app.dependency_overrides[get_settings_dep] = lambda: settings

        if introspection_response is not None:
            mock_client = AsyncMock()
            mock_client.introspect = AsyncMock(return_value=introspection_response)
            app.dependency_overrides[get_introspection_client] = lambda: mock_client
        else:
            app.dependency_overrides[get_introspection_client] = lambda: None

        cache = IntrospectionCache(ttl_s=30)
        app.dependency_overrides[get_introspection_cache] = lambda: cache
        return app

    return _build


# ---------------------------------------------------------------------------
# (a) PAT JWT (RFC 7662 introspection fallback)
# ---------------------------------------------------------------------------
class TestPatJwtIntrospection:
    def test_active_pat_with_invoke_scope_passes_scoped_route(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        response = IntrospectionResponse(
            active=True,
            sub="user-7",
            tenant="tenant-7",
            scope=["bsage:mcp:invoke"],
        )
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/api/mcp/scoped_invoke",
            headers={"Authorization": f"Bearer {_make_pat_jwt('pat-active')}"},
        )
        assert resp.status_code == 200, resp.text

    def test_active_pat_with_invoke_scope_passes_list_plugins(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        response = IntrospectionResponse(
            active=True,
            sub="user-7",
            tenant="tenant-7",
            scope=["bsage:mcp:invoke"],
        )
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/api/mcp/list_plugins",
            headers={"Authorization": f"Bearer {_make_pat_jwt('pat-active')}"},
        )
        assert resp.status_code == 200, resp.text

    def test_active_pat_without_invoke_scope_returns_403(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        # Token is active (auth OK) but lacks the required scope.
        response = IntrospectionResponse(
            active=True,
            sub="user-7",
            tenant="tenant-7",
            scope=["bsage:read"],
        )
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/api/mcp/scoped_invoke",
            headers={"Authorization": f"Bearer {_make_pat_jwt('pat-no-scope')}"},
        )
        assert resp.status_code == 403
        assert "bsage:mcp:invoke" in resp.json()["detail"]

    def test_inactive_pat_returns_401(self, app_factory: Callable[..., FastAPI]) -> None:
        response = IntrospectionResponse(active=False)
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/api/mcp/list_plugins",
            headers={"Authorization": f"Bearer {_make_pat_jwt('pat-revoked')}"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# (b) Service JWT (Phase 0 P0.5 invariant)
# ---------------------------------------------------------------------------
class TestServiceJwt:
    def test_service_jwt_passes_mcp_route(self, app_factory: Callable[..., FastAPI]) -> None:
        token = jwt.encode(
            {
                "sub": "service:bsnexus",
                "aud": "bsage",
                "iss": "https://auth.bsvibe.dev",
                "iat": 1700000000,
                "exp": 1900000000,
                "scope": "bsage:read",
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
# (c) Invalid / missing token
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
