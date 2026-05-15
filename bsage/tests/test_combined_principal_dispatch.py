"""combined_principal("bsage") dispatch (PAT JWT / user JWT / service JWT).

BSage wires its HTTP principal to the shared
``bsvibe_authz.combined_principal("bsage")`` dep. That factory accepts
``aud=bsage`` service JWTs AND falls through to ``get_current_user``
(user JWT / PAT JWT via RFC 7662 introspection).

Tier 2 cleanup (bsvibe-authz 1.3.0, 2026-05): the legacy ``bsv_sk_*``
opaque-prefix dispatch was removed. The only path now reaching
introspection is the JWT-shaped fallback — PAT JWTs are minted by
BSVibe-Auth's device-authorization grant, signed with
``SERVICE_TOKEN_SIGNING_SECRET`` (not ``USER_JWT_SECRET``), so they
fail ``verify_user_jwt`` locally and only succeed via
``/oauth/introspect``. We forge that shape in the test below.

This module pins all three paths end-to-end against the *library* dep so
BSage's principal resolution stays standard and is not re-implemented.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock

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
from bsvibe_authz.settings import Settings as AuthzSettings
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

_USER_JWT_SECRET = "test-user-secret"  # noqa: S105
_SERVICE_TOKEN_SECRET = "test-service-secret"  # noqa: S105
# A secret neither verifier shares — produces a JWT-shaped token that
# fails both ``verify_user_jwt`` and ``verify_service_jwt`` locally and
# therefore reaches the introspection fallback in ``get_current_user``.
_PAT_JWT_SECRET = "test-pat-unknown-secret"  # noqa: S105


def _make_pat_jwt(jti: str = "pat-abc") -> str:
    """Build a JWT-shaped token that drops into introspection fallback."""
    return jwt.encode(
        {"jti": jti, "iat": 1700000000, "exp": 1900000000},
        _PAT_JWT_SECRET,
        algorithm="HS256",
    )


# The dep BSage installs as ``state.get_current_user``.
_bsage_principal = combined_principal("bsage")


def _build_settings() -> AuthzSettings:
    return AuthzSettings(
        bsvibe_auth_url="https://auth.bsvibe.dev",
        openfga_api_url="",
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
def app_factory() -> Callable[..., FastAPI]:
    def _build(introspection_response: IntrospectionResponse | None = None) -> FastAPI:
        app = FastAPI()

        @app.get("/whoami")
        async def whoami(user: User = Depends(_bsage_principal)) -> dict:
            return {
                "id": user.id,
                "scope": list(user.scope),
                "is_service": user.is_service,
                "active_tenant_id": user.active_tenant_id,
            }

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


class TestPatIntrospectionPath:
    def test_active_pat_jwt_resolves_to_user_via_introspection(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        response = IntrospectionResponse(
            active=True,
            sub="user-42",
            tenant="tenant-x",
            scope=["bsage.mcp-invoke"],
        )
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/whoami",
            headers={"Authorization": f"Bearer {_make_pat_jwt('pat-abc')}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == "user-42"
        assert body["scope"] == ["bsage.mcp-invoke"]
        assert body["is_service"] is False
        assert body["active_tenant_id"] == "tenant-x"

    def test_inactive_pat_jwt_returns_401(self, app_factory: Callable[..., FastAPI]) -> None:
        response = IntrospectionResponse(active=False)
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/whoami",
            headers={"Authorization": f"Bearer {_make_pat_jwt('pat-revoked')}"},
        )
        assert resp.status_code == 401

    def test_legacy_opaque_prefix_no_longer_dispatches_to_introspection(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        """Tier 2 retirement guard: a ``bsv_sk_*`` token is now treated as
        any non-JWT garbage — it fails ``_looks_like_jwt`` and skips
        introspection entirely, returning 401 even when an introspection
        response is wired up that would have resolved it under 1.2.0."""
        response = IntrospectionResponse(
            active=True,
            sub="user-42",
            tenant="tenant-x",
            scope=["bsage.mcp-invoke"],
        )
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/whoami",
            headers={"Authorization": "Bearer bsv_sk_abc"},
        )
        assert resp.status_code == 401


class TestUserJwtPath:
    def test_valid_user_jwt_resolves_to_user(self, app_factory: Callable[..., FastAPI]) -> None:
        token = jwt.encode(
            {
                "sub": "user-7",
                "email": "u7@bsvibe.dev",
                "active_tenant_id": "tenant-7",
                "aud": "bsvibe",
                "iss": "https://auth.bsvibe.dev",
                "iat": 1700000000,
                "exp": 1900000000,
            },
            _USER_JWT_SECRET,
            algorithm="HS256",
        )
        client = TestClient(app_factory())
        resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == "user-7"
        assert body["is_service"] is False
        assert body["active_tenant_id"] == "tenant-7"


class TestServiceJwtPath:
    def test_valid_service_jwt_resolves_to_service_principal(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        token = jwt.encode(
            {
                "sub": "service:bsnexus",
                "aud": "bsage",
                "iss": "https://auth.bsvibe.dev",
                "iat": 1700000000,
                "exp": 1900000000,
                "scope": "bsage:knowledge.read",
                "token_type": "service",
                "tenant_id": "tenant-default",
            },
            _SERVICE_TOKEN_SECRET,
            algorithm="HS256",
        )
        client = TestClient(app_factory())
        resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == "service:bsnexus"
        assert body["is_service"] is True
        assert body["active_tenant_id"] == "tenant-default"


class TestNoCredentials:
    def test_missing_authorization_returns_401(self, app_factory: Callable[..., FastAPI]) -> None:
        client = TestClient(app_factory())
        resp = client.get("/whoami")
        assert resp.status_code == 401

    def test_invalid_jwt_returns_401(self, app_factory: Callable[..., FastAPI]) -> None:
        client = TestClient(app_factory())
        resp = client.get("/whoami", headers={"Authorization": "Bearer not.a.jwt"})
        assert resp.status_code == 401
