"""Authentication module for the BSage Gateway.

Provides factory functions that create a SupabaseAuthProvider and a FastAPI
dependency based on application settings.  When ``supabase_jwt_secret`` is
empty the auth layer is disabled and an anonymous stub user is returned.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog
from bsvibe_auth import BSVibeUser, SupabaseAuthProvider
from bsvibe_auth.fastapi import create_auth_dependency

if TYPE_CHECKING:
    from bsage.core.config import Settings

logger = structlog.get_logger(__name__)


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


def create_get_current_user(
    provider: SupabaseAuthProvider | None,
) -> Callable:
    """Return a FastAPI dependency that resolves the current user.

    When *provider* is ``None`` the dependency always returns an anonymous
    ``BSVibeUser`` so that the application works without authentication.
    """
    if provider is not None:
        return create_auth_dependency(provider)

    async def _anonymous_user() -> BSVibeUser:
        return _ANONYMOUS_USER

    return _anonymous_user
