"""Stdio transport for the BSage MCP server.

Entry point for the ``bsage-mcp`` console script. Runs an MCP server
over stdin/stdout — the protocol Claude Desktop uses.

CRITICAL: stdio MCP uses stdout for JSON-RPC framing. Any library that
prints to stdout (structlog defaults, click banners, etc.) corrupts the
stream. ``_configure_stdio_logging`` redirects all logging to stderr
before the server starts.

Principal threading: the stdio transport has no per-request HTTP
headers, so a permissioned MCP tool would otherwise see ``ctx.user is
None`` and deny every call. When ``BSAGE_MCP_PAT`` is set,
``run_stdio_server`` resolves that PAT once at startup — through the
same ``bsvibe_authz`` dispatch the Streamable HTTP transport uses — and
pins the principal on ``state.mcp_principal`` so
:func:`bsage.mcp.server._resolve_principal` returns it for every stdio
call. Unset → the principal is ``None`` (a single trusted local
process: domain read tools, ``required_permission=None``, still work;
permissioned tools deny). This mirrors BSupervisor's stdio transport.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import structlog

STDIO_TOKEN_ENV = "BSAGE_MCP_PAT"
"""Env var carrying the PAT used to authenticate stdio MCP calls."""


def _configure_stdio_logging() -> None:
    """Send all logs to stderr so the JSON-RPC stdout channel stays clean."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    root = logging.getLogger()
    # Replace any existing handlers — some test runners or env loaders
    # may have wired stdout handlers already.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    structlog.configure(
        processors=[structlog.processors.JSONRenderer()],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


async def _resolve_stdio_principal(state: Any) -> Any | None:
    """Resolve the MCP principal for the stdio transport.

    Reads a PAT from ``$BSAGE_MCP_PAT`` and authenticates it through the
    same ``bsvibe_authz`` dispatch the Streamable HTTP transport uses
    (:func:`bsage.mcp.streamable_http.resolve_principal_from_headers`),
    so the stdio and HTTP transports share one resolution path. Returns
    ``None`` when the env var is unset/blank, or when the PAT is invalid
    (the resolver never raises — an auth failure resolves to anonymous).
    """
    pat = os.environ.get(STDIO_TOKEN_ENV, "").strip()
    if not pat:
        return None
    from bsage.mcp.streamable_http import resolve_principal_from_headers

    return await resolve_principal_from_headers({"authorization": f"Bearer {pat}"}, state)


async def run_stdio_server() -> None:
    """Bring up the MCP stdio server with a fully wired AppState."""
    from mcp.server.stdio import stdio_server

    from bsage.core.config import get_settings
    from bsage.gateway.dependencies import AppState
    from bsage.mcp.server import build_server

    _configure_stdio_logging()

    state = AppState(get_settings())
    await state.initialize()
    try:
        # Pin the principal so permissioned tools authorize on stdio.
        state.mcp_principal = await _resolve_stdio_principal(state)
        server = build_server(state)
        async with stdio_server() as (read_stream, write_stream):
            init_options = server.create_initialization_options()
            await server.run(read_stream, write_stream, init_options)
    finally:
        await state.shutdown()


def main() -> None:
    """Console-script entry point — `bsage-mcp`."""
    try:
        asyncio.run(run_stdio_server())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
