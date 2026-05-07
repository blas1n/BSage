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

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from mcp.server.sse import SseServerTransport
from starlette.responses import Response

logger = structlog.get_logger(__name__)


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
        """Authenticate the SSE request via bsvibe-authz.

        EventSource can't send Authorization headers, so we accept
        ``?token=`` as a fallback and inject it as a Bearer header
        before delegating to ``state.get_current_user`` (combined
        bootstrap → opaque → JWT dispatch).
        """
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
