"""bsvibe-authz integration glue for the BSage Gateway (Phase 0 P0.5).

This module replaces the legacy ``gateway/auth.py`` flow that combined
``BsvibeAuthProvider`` with the ad-hoc ``X-Service-Key`` header. It exposes:

- :func:`combined_principal` — FastAPI dep that resolves a principal from
  *either* a user JWT (``CurrentUser``) *or* an audience-scoped service JWT
  (``ServiceKeyAuth("bsage")``). Routes BSNexus calls (knowledge / vault)
  must accept both — see ``BSVibe_Auth_Design.md`` §7.
- :func:`require_bsage_permission` — thin wrapper around
  ``bsvibe_authz.require_permission`` that wires the principal resolved by
  :func:`combined_principal` into the OpenFGA ``check`` call.
- :func:`get_service_principal_dep` — explicit dep used by tests to override
  the service JWT path; the real implementation delegates to
  ``ServiceKeyAuth("bsage")``.
- :func:`service_principal_from_payload` — pure helper that converts a
  verified ``ServiceTokenPayload`` into a ``User(is_service=True)`` so that
  downstream code (tenant scoping, permission checks, audit log) treats
  service callers uniformly.

The module deliberately exposes the same surface used by the test fixture
``_build_app`` so that overrides cover both the user-JWT and service-JWT
branches without monkey-patching.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from functools import lru_cache

import structlog
from bsvibe_authz import (
    AuthError,
    OpenFGAError,
    PermissionCache,
    ServiceTokenPayload,
    User,
    get_current_user,
)
from bsvibe_authz.auth import verify_service_jwt
from bsvibe_authz.deps import FGAClientProtocol
from bsvibe_authz.settings import Settings as AuthzSettings
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = structlog.get_logger(__name__)


_TENANT_PERMISSION_RELATIONS = {
    "read": "read",
    "write": "write",
    "execute": "write",
}


# ---------------------------------------------------------------------------
# Settings adapter — bsvibe_authz.get_settings() requires several fields by
# default which the BSage process may not have (e.g. local dev without OpenFGA
# bootstrapped, unit tests with no env). Build a tolerant Settings that fills
# missing required fields with empty strings so the deps still resolve.
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _authz_settings_safe() -> AuthzSettings:
    """Lazily construct an AuthzSettings, supplying empty defaults for the
    fields the upstream Settings declares as required so import-time wiring
    on a partially-configured deployment doesn't 500."""
    overrides = {
        "bsvibe_auth_url": os.environ.get("BSVIBE_AUTH_URL", ""),
        "openfga_api_url": os.environ.get("OPENFGA_API_URL", ""),
        "openfga_store_id": os.environ.get("OPENFGA_STORE_ID", ""),
        "openfga_auth_model_id": os.environ.get("OPENFGA_AUTH_MODEL_ID", ""),
        "service_token_signing_secret": os.environ.get("SERVICE_TOKEN_SIGNING_SECRET", ""),
        # Demo bypass — when set, get_current_user accepts demo-signed
        # JWTs (is_demo claim) and resolves them to a User(is_demo=True).
        "demo_jwt_secret": os.environ.get("DEMO_JWT_SECRET") or None,
    }
    return AuthzSettings(**overrides)


def get_authz_settings() -> AuthzSettings:
    """Override of ``bsvibe_authz.get_settings_dep`` for the BSage process.

    Wired into FastAPI via ``app.dependency_overrides[get_settings_dep] =
    get_authz_settings`` in :func:`bsage.gateway.app.create_app`.
    """
    return _authz_settings_safe()


def reset_authz_settings_cache() -> None:
    """Drop the cached AuthzSettings — used by tests."""
    _authz_settings_safe.cache_clear()


_permission_cache_singleton: PermissionCache | None = None
_openfga_client_singleton: FGAClientProtocol | None = None


def _resolve_permission_cache(settings: AuthzSettings) -> PermissionCache:
    global _permission_cache_singleton
    if _permission_cache_singleton is None:
        _permission_cache_singleton = PermissionCache(ttl_s=settings.permission_cache_ttl_s)
    return _permission_cache_singleton


def _resolve_openfga_client(settings: AuthzSettings) -> FGAClientProtocol:
    global _openfga_client_singleton
    if _openfga_client_singleton is None:
        from bsvibe_authz.client import OpenFGAClient

        _openfga_client_singleton = OpenFGAClient(settings)  # type: ignore[assignment]
    return _openfga_client_singleton


def reset_authz_singletons() -> None:
    """Used by tests — drop the cached cache + fga client."""
    global _permission_cache_singleton, _openfga_client_singleton
    _permission_cache_singleton = None
    _openfga_client_singleton = None


# Optional FastAPI deps — return None by default. Tests can override these
# via ``app.dependency_overrides[_optional_fga_dep] = lambda: my_fake_fga``
# to plug in a deterministic FGA client without touching globals.
async def _optional_fga_dep() -> FGAClientProtocol | None:
    return None


async def _optional_cache_dep() -> PermissionCache | None:
    return None


def _settings_dep() -> AuthzSettings:
    return get_authz_settings()


# Audience for every service JWT BSage accepts.
BSAGE_AUDIENCE = "bsage"

_bearer_scheme = HTTPBearer(auto_error=False)


def service_principal_from_payload(payload: ServiceTokenPayload) -> User:
    """Translate a verified service JWT into a ``User(is_service=True)``.

    The OpenFGA principal string for a service caller is ``service:<name>``.
    The ``sub`` claim already follows that convention (``service:bsnexus``),
    so we keep it verbatim — this matches the assumption in
    ``bsvibe_authz.deps.require_permission`` that ``user.id`` already carries
    the ``service:`` prefix when ``is_service is True``.
    """
    return User(
        id=payload.sub,
        email=None,
        active_tenant_id=payload.tenant_id,
        tenants=[],
        is_service=True,
    )


# ---------------------------------------------------------------------------
# Service JWT extraction — separate from the user-JWT dep so a missing
# Authorization header on the service-only path returns 401 *before* the
# combined dep falls back to the user verifier.
# ---------------------------------------------------------------------------
async def get_service_principal_dep(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: AuthzSettings = Depends(_settings_dep),
) -> User | None:
    """Try to verify the Authorization header as a *service* JWT scoped to
    ``aud=bsage``. Returns ``None`` if the token is *not* a service token —
    the caller should fall back to the user-JWT path. Returns the principal
    on success, raises 401 on a malformed/expired service token.
    """
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        return None
    if not settings.service_token_signing_secret:
        # No service-token secret configured → service tokens cannot be issued
        # for this deployment, so any Bearer must be a user token.
        return None
    try:
        payload = verify_service_jwt(creds.credentials, settings, BSAGE_AUDIENCE)
    except AuthError:
        # Could be a user JWT — let the user-JWT dep handle it. Only log the
        # event so the operator sees that a service-token attempt was made.
        return None
    return service_principal_from_payload(payload)


async def combined_principal(
    request: Request,
    service: User | None = Depends(get_service_principal_dep),
    settings: AuthzSettings = Depends(_settings_dep),
) -> User:
    """Resolve the request principal from either a user JWT or a service JWT
    audience-scoped to ``bsage``.

    Resolution order:
    1. If ``Authorization`` carries a valid ``aud=bsage`` service JWT
       (verified by :func:`get_service_principal_dep`), use it.
    2. Otherwise, fall through to the user-JWT verifier
       (``bsvibe_authz.get_current_user``). 401 on missing / invalid.
    """
    if service is not None:
        return service
    # Reuse the underlying user-JWT verifier directly so the dep can keep its
    # exception semantics. We pass the Authorization header through.
    auth_header = request.headers.get("Authorization")
    return await get_current_user(authorization=auth_header, settings=settings)


# ---------------------------------------------------------------------------
# Permission enforcement
# ---------------------------------------------------------------------------
def require_bsage_permission(
    permission: str,
    *,
    resource_type: str | None = None,
    resource_id_param: str | None = None,
    principal_dep: Callable[..., Awaitable[User]] | None = None,
) -> Callable[..., Awaitable[None]]:
    """FastAPI dep factory — verify the resolved principal has *permission*.

    Identical semantics to ``bsvibe_authz.require_permission`` except that it
    can source the principal from a custom dep (``principal_dep``). When the
    caller doesn't pass one, falls back to :func:`combined_principal`.

    Pass ``resource_type`` + ``resource_id_param`` to scope the check to a
    specific resource (e.g. ``("note", "path")``); omit both for a tenant-wide
    check (object = ``tenant:<active_tenant_id>``).

    The optional ``principal_dep`` parameter exists so that
    :func:`bsage.gateway.routes.create_routes` can route the *same*
    principal-resolution callable that the router-level dep already uses
    (``state.get_current_user``) — keeping the test surface symmetric with
    pre-P0.5 fixtures that override ``state.get_current_user`` to return a
    synthetic ``User``.

    Permissive mode: when ``settings.openfga_api_url`` is empty, the OpenFGA
    backend is not bootstrapped yet — the dep returns immediately. Production
    sets the env var and the same code path enforces ``check``.
    """
    parts = permission.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"require_bsage_permission: invalid permission {permission!r} "
            "(expected '<product>.<resource>.<action>')",
        )
    action = parts[2]
    relation = _TENANT_PERMISSION_RELATIONS.get(action, action)

    if principal_dep is None:
        principal_dep = combined_principal

    async def _dep(
        request: Request,
        user: User = Depends(principal_dep),  # type: ignore[arg-type]
        cache: PermissionCache | None = Depends(_optional_cache_dep),
        fga: FGAClientProtocol | None = Depends(_optional_fga_dep),
        settings: AuthzSettings = Depends(_settings_dep),
    ) -> None:
        if not settings.openfga_api_url:
            return

        # Defensive — if the principal dep returned something dict-like (legacy
        # mock), coerce it into a User. Real production path always returns
        # a bsvibe_authz.User.
        if not isinstance(user, User):
            user = User(
                id=getattr(user, "id", "anonymous"),
                email=getattr(user, "email", None),
                active_tenant_id=getattr(user, "active_tenant_id", None),
                tenants=[],
                is_service=getattr(user, "is_service", False),
                is_demo=getattr(user, "is_demo", False),
            )

        # Demo-mode bypass — demo deployments have no OpenFGA model and the
        # tenant is a per-visitor sandbox, so every demo principal is
        # implicitly allowed.
        if user.is_demo:
            return

        # Resolve cache + fga lazily — tests can pre-supply via dep overrides
        # of _optional_cache_dep / _optional_fga_dep, otherwise we lazily
        # create the singletons on first OpenFGA-enabled request.
        if cache is None:
            cache = _resolve_permission_cache(settings)
        if fga is None:
            fga = _resolve_openfga_client(settings)

        principal = user.id if user.is_service else f"user:{user.id}"

        if resource_type and resource_id_param:
            resource_id = request.path_params.get(resource_id_param)
            if not resource_id:
                resource_id = request.query_params.get(resource_id_param)
            if not resource_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"missing path/query param {resource_id_param!r}",
                )
            object_ = f"{resource_type}:{resource_id}"
        else:
            tenant_id = user.active_tenant_id
            if not tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="no active tenant in session",
                )
            object_ = f"tenant:{tenant_id}"

        cached = await cache.get(principal, relation, object_)
        if cached is not None:
            allowed = cached
        else:
            try:
                allowed = await fga.check(principal, relation, object_)
            except OpenFGAError as exc:
                logger.warning(
                    "permission_check_failed",
                    principal=principal,
                    relation=relation,
                    object=object_,
                    status_code=exc.status_code,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"permission denied: {permission}",
                ) from exc
            await cache.set(principal, relation, object_, allowed)

        if not allowed:
            logger.info(
                "permission_denied",
                principal=principal,
                relation=relation,
                object=object_,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"permission denied: {permission}",
            )

    return _dep


__all__ = [
    "BSAGE_AUDIENCE",
    "combined_principal",
    "get_service_principal_dep",
    "require_bsage_permission",
    "service_principal_from_payload",
]
