"""Streamable HTTP transport for the BSage MCP server.

Exposes the MCP server (built by :func:`bsage.mcp.server.build_server`)
to remote clients (Claude Code, IDE plugins, BSNexus service-to-service
runs) over the MCP-spec **Streamable HTTP** transport, mounted at
``/mcp``. This replaces the legacy SSE transport and unifies BSage with
the other three BSVibe products (BSGateway / BSNexus / BSupervisor),
which all serve Streamable HTTP at ``/mcp``.

Why Streamable HTTP over SSE — and the bug it fixes:

The SSE transport authenticated the *connection* (``GET /mcp/sse``) but
the MCP SDK's ``CallTool`` path does not carry HTTP headers down to the
tool handler, so the per-call :class:`bsage.mcp.api.ToolContext` had no
principal — ``ctx.user`` was ``None`` and every permissioned tool denied.
Streamable HTTP carries the ``Authorization`` header on *every* request,
so this module captures it per-request into a context-var that the
dispatcher (:func:`bsage.mcp.server._dispatch_via_registry`) reads — the
real principal threads into ``ToolContext.user``.

The transport is stateless + JSON-response: agent clients are
request/response shaped today and BSage runs no MCP session store.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar
from typing import Any

import structlog
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Per-request principal — populated by the ASGI shim, read by the dispatcher.
# ---------------------------------------------------------------------------
_mcp_principal_var: ContextVar[Any | None] = ContextVar(
    "_bsage_mcp_principal",
    default=None,
)
"""Per-request resolved principal (a ``bsvibe_authz.User`` or duck-type).

The MCP SDK's ``CallTool`` path does not thread HTTP headers down to the
tool handler, so the Streamable HTTP ASGI shim resolves the principal
from the ``Authorization`` header and stashes it here. The dispatcher
(:func:`bsage.mcp.server._dispatch_via_registry`) reads it back so
``ToolContext.user`` is the real principal — not ``None``.

``None`` (the default outside an active MCP request, or when the request
carried no/invalid auth) makes permissioned tools deny, exactly as the
``ToolRegistry`` contract requires. ``None`` rather than a mutable
default keeps ruff B039 happy.
"""


def get_request_principal() -> Any | None:
    """Return the principal resolved for the current MCP request, if any."""
    return _mcp_principal_var.get()


async def resolve_principal_from_headers(
    headers: Mapping[str, str],
    state: Any,
) -> Any | None:
    """Authenticate an MCP request from raw HTTP headers.

    Delegates to ``bsvibe_authz.deps.get_current_user`` — the same
    opaque → user-JWT → PAT-introspection dispatch the REST surface and
    ``combined_principal`` run. Returns the resolved principal, or
    ``None`` when no/invalid credentials were supplied (a permissioned
    tool then denies; an unpermissioned domain read tool still works).

    ``state`` carries BSage's ``AppState``; only used as a hook point
    for tests that want to stub the resolution. Production resolution
    goes straight through ``bsvibe_authz``.
    """
    auth_header = headers.get("authorization") or headers.get("Authorization")
    active_tenant = headers.get("x-active-tenant") or headers.get("X-Active-Tenant")
    if not auth_header:
        return None
    try:
        from bsvibe_authz import get_settings
        from bsvibe_authz.deps import (
            get_current_user,
            get_introspection_cache,
            get_introspection_client,
        )

        authz_settings = get_settings()
        return await get_current_user(
            authorization=auth_header,
            x_active_tenant=active_tenant,
            settings=authz_settings,
            introspection_client=get_introspection_client(authz_settings),
            introspection_cache=get_introspection_cache(authz_settings),
        )
    except Exception:  # noqa: BLE001 — auth failure → anonymous, never 500
        logger.warning("mcp_streamable_auth_failed", exc_info=True)
        return None


def build_streamable_http_app(
    state: Any,
) -> tuple[StreamableHTTPSessionManager, Callable[..., Any]]:
    """Return ``(manager, asgi_app)`` for the BSage ``/mcp`` HTTP transport.

    ``manager.run()`` MUST be entered by the FastAPI lifespan before the
    first request arrives — the SDK creates its task group there and
    per-request handlers raise ``RuntimeError`` otherwise.

    The returned ASGI app is what the lifespan mounts at ``/mcp``: it
    decodes the incoming HTTP headers, resolves the principal from the
    ``Authorization`` header, stashes it on :data:`_mcp_principal_var`
    so the dispatcher threads it into ``ToolContext.user``, then
    delegates to ``manager.handle_request``.
    """
    from bsage.mcp.server import build_server

    server = build_server(state)
    manager = StreamableHTTPSessionManager(
        app=server,
        stateless=True,
        json_response=True,
    )

    async def asgi_app(scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await manager.handle_request(scope, receive, send)
            return
        raw_headers = scope.get("headers", []) or []
        decoded: dict[str, str] = {}
        for k, v in raw_headers:
            try:
                decoded[k.decode("latin-1").lower()] = v.decode("latin-1")
            except (AttributeError, UnicodeDecodeError):  # pragma: no cover
                continue
        principal = await resolve_principal_from_headers(decoded, state)
        token = _mcp_principal_var.set(principal)
        try:
            await manager.handle_request(scope, receive, send)
        finally:
            _mcp_principal_var.reset(token)

    return manager, asgi_app


__all__ = [
    "build_streamable_http_app",
    "get_request_principal",
    "resolve_principal_from_headers",
]
