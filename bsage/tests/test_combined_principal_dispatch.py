"""combined_principal dispatch (opaque / user JWT / service JWT).

The Phase 0 P0.5 path accepts service JWTs (aud=bsage) AND user JWTs.
Token cutover extends ``combined_principal`` to also accept the opaque
``bsv_sk_*`` session token via RFC 7662 introspection.

This module pins all three paths end-to-end so the dispatch stays wired
to ``bsvibe_authz.get_current_user`` rather than diverging into a private
re-implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock

import jwt
import pytest
from bsvibe_authz import IntrospectionResponse, User
from bsvibe_authz.cache import IntrospectionCache
from bsvibe_authz.settings import Settings as AuthzSettings
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from bsage.gateway.authz import (
    _get_introspection_cache_dep,
    _get_introspection_client_dep,
    _settings_dep,
    combined_principal,
)

_USER_JWT_SECRET = "test-user-secret"  # noqa: S105
_SERVICE_TOKEN_SECRET = "test-service-secret"  # noqa: S105


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
        async def whoami(user: User = Depends(combined_principal)) -> dict:
            return {
                "id": user.id,
                "scope": list(user.scope),
                "is_service": user.is_service,
                "active_tenant_id": user.active_tenant_id,
            }

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


class TestOpaquePath:
    def test_active_opaque_token_resolves_to_user(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        response = IntrospectionResponse(
            active=True,
            sub="user-42",
            tenant="tenant-x",
            scope=["sage.mcp-invoke"],
        )
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/whoami",
            headers={"Authorization": "Bearer bsv_sk_abc"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == "user-42"
        assert body["scope"] == ["sage.mcp-invoke"]
        assert body["is_service"] is False
        assert body["active_tenant_id"] == "tenant-x"

    def test_inactive_opaque_token_returns_401(self, app_factory: Callable[..., FastAPI]) -> None:
        response = IntrospectionResponse(active=False)
        client = TestClient(app_factory(introspection_response=response))
        resp = client.get(
            "/whoami",
            headers={"Authorization": "Bearer bsv_sk_revoked"},
        )
        assert resp.status_code == 401

    def test_opaque_token_falls_through_to_jwt_when_introspection_disabled(
        self, app_factory: Callable[..., FastAPI]
    ) -> None:
        # introspection_response=None → introspection_client dep returns None.
        # bsv_sk_* token then drops into the JWT verifier, which 401s on a
        # non-JWT shape.
        client = TestClient(app_factory(introspection_response=None))
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
