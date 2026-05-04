"""SSE transport mount for the BSage MCP server.

Exposes the same MCP server (built by ``bsage.mcp.server.build_server``)
to remote clients (Cursor, BSNexus runs, ad-hoc HTTP clients) over the
MCP-spec Server-Sent-Events transport.

Auth note: ``EventSource`` cannot send Authorization headers, so the
``GET /mcp/sse`` route accepts a ``?token=`` query fallback. Identical
pattern to BSNexus integration (BSNexus_BSGateway_Integration §4 —
documented as ``eventsource-sse-auth-trap``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from mcp.server.sse import SseServerTransport
from starlette.responses import Response

from bsage.mcp.api_keys import TOKEN_PREFIX

logger = structlog.get_logger(__name__)


@dataclass
class _MCPKeyPrincipal:
    """Synthetic principal for MCP requests authenticated via a PAT.

    Mirrors the shape of the real ``bsvibe_authz.User`` enough that
    downstream tools that read ``id`` / ``active_tenant_id`` keep working.
    """

    id: str
    active_tenant_id: str | None
    auth_method: str = "mcp_api_key"


def create_sse_routes(state: Any) -> APIRouter:
    """Mount MCP-over-SSE endpoints on the gateway."""
    from bsage.mcp.server import build_server

    router = APIRouter(prefix="/mcp", tags=["mcp"])
    transport = SseServerTransport("/mcp/messages/")
    server = build_server(state)

    async def _resolve_principal(
        request: Request,
        token: str | None = Query(default=None),
    ) -> Any:
        """Get the current user — try MCP API key first, then JWT.

        EventSource can't send Authorization, so we accept ?token=
        as well. PAT tokens (bsg_mcp_*) bypass bsvibe-auth entirely
        and validate against the MCPAPIKeyStore.
        """
        # Pull the bearer token from header if no query token
        bearer = token
        if not bearer:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                bearer = auth[7:]

        # Path 1 — MCP PAT
        if bearer and bearer.startswith(TOKEN_PREFIX):
            record = await state.mcp_api_keys.verify(bearer)
            if record is None:
                raise HTTPException(status_code=401, detail="Invalid or revoked API key")
            return _MCPKeyPrincipal(
                id=record.user_id or f"mcp-key:{record.id}",
                active_tenant_id=record.tenant_id,
            )

        # Path 2 — fall back to JWT via bsvibe-auth (?token= in query)
        if token and "authorization" not in {k.lower() for k in request.headers}:
            request.scope["headers"] = [
                *request.scope["headers"],
                (b"authorization", f"Bearer {token}".encode()),
            ]
        try:
            return await state.get_current_user(request)
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("mcp_sse_auth_failed", exc_info=True)
            raise HTTPException(status_code=401, detail="Unauthorized") from exc

    @router.get("/sse")
    async def sse_endpoint(
        request: Request,
        _principal: Any = Depends(_resolve_principal),
    ) -> Response:
        async with transport.connect_sse(request.scope, request.receive, request._send) as (
            read,
            write,
        ):
            await server.run(read, write, server.create_initialization_options())
        return Response()

    @router.post("/messages/{path:path}")
    async def messages_endpoint(request: Request) -> Response:
        # The SseServerTransport hands back its own ASGI handler for the
        # POST half of the protocol. Defer to it.
        return await transport.handle_post_message(request.scope, request.receive, request._send)

    return router
