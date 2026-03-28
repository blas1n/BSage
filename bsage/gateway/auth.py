"""Authentication module for the BSage Gateway.

Provides factory functions that create a SupabaseAuthProvider and a FastAPI
dependency based on application settings.  When ``supabase_jwt_secret`` is
empty the auth layer is disabled and an anonymous stub user is returned.

Service-to-service calls are supported via an ``X-Service-Key`` header.
When a request carries a valid service key, the caller is represented as a
``BSVibeUser`` with ``role="service_role"``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog
from bsvibe_auth import AuthError, BSVibeUser, SupabaseAuthProvider
from bsvibe_auth.fastapi import create_auth_dependency
from fastapi import HTTPException, Request, status

if TYPE_CHECKING:
    from bsage.core.config import Settings

logger = structlog.get_logger(__name__)

_SERVICE_KEY_HEADER = "X-Service-Key"


def create_auth_provider(settings: Settings) -> SupabaseAuthProvider | None:
    """Create a SupabaseAuthProvider if credentials are configured.

    Returns ``None`` when ``supabase_jwt_secret`` is empty, which disables
    authentication entirely (all endpoints are open).
    """
    if not settings.supabase_jwt_secret:
        logger.info("auth_disabled", reason="supabase_jwt_secret is empty")
        return None

    provider = SupabaseAuthProvider(
        jwt_secret=settings.supabase_jwt_secret,
        supabase_url=settings.supabase_url or None,
        service_role_key=settings.supabase_service_role_key or None,
    )
    logger.info("auth_enabled", supabase_url=settings.supabase_url or "(not set)")
    return provider


_ANONYMOUS_USER = BSVibeUser(id="anonymous", email=None, role="anon")


def _resolve_service_key(
    request: Request,
    service_api_keys: dict[str, str],
) -> BSVibeUser | None:
    """Check for a valid ``X-Service-Key`` header.

    Returns a ``BSVibeUser`` with ``role="service_role"`` when the key
    matches a configured service, or ``None`` otherwise.
    """
    key = request.headers.get(_SERVICE_KEY_HEADER)
    if not key:
        return None
    for service_name, expected_key in service_api_keys.items():
        if key == expected_key:
            logger.info("service_auth_ok", service=service_name)
            return BSVibeUser(id=service_name, email=None, role="service_role")
    return None


def create_get_current_user(
    provider: SupabaseAuthProvider | None,
    *,
    service_api_keys: dict[str, str] | None = None,
) -> Callable:
    """Return a FastAPI dependency that resolves the current user.

    Authentication is attempted in order:

    1. ``X-Service-Key`` header — matched against *service_api_keys*.
    2. ``Authorization: Bearer <jwt>`` — validated by *provider*.
    3. If *provider* is ``None``, returns an anonymous ``BSVibeUser``.
    """
    _keys = service_api_keys or {}
    jwt_dependency = create_auth_dependency(provider) if provider is not None else None

    async def _get_current_user(request: Request) -> BSVibeUser:
        # 1. Service API key
        if _keys:
            svc_user = _resolve_service_key(request, _keys)
            if svc_user is not None:
                return svc_user

        # 2. JWT Bearer token
        if jwt_dependency is not None:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[len("Bearer ") :]
                try:
                    return await provider.verify_token(token)  # type: ignore[union-attr]
                except AuthError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=exc.message,
                        headers={"WWW-Authenticate": "Bearer"},
                    ) from exc

            # No service key, no Bearer token → service key was wrong or missing
            if request.headers.get(_SERVICE_KEY_HEADER):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid service key",
                )

            # No credentials at all
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 3. Auth disabled — anonymous
        return _ANONYMOUS_USER

    return _get_current_user
