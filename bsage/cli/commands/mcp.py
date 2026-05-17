"""``bsage mcp`` Typer sub-app — MCP transport launcher + introspection.

Subcommands:

* ``serve [--transport stdio|http]`` — bring up the MCP server.
  ``stdio`` hands off to :func:`bsage.mcp.stdio.run_stdio_server`
  (the same path Claude Desktop hits via the ``bsage-mcp`` console
  script). ``http`` runs ``uvicorn.run(create_app(...))`` so the
  Streamable HTTP transport mounted at ``/mcp`` shares the gateway
  lifespan.
* ``list-tools`` — build the in-process :class:`ToolRegistry` and emit
  the catalog (name + description + required_permission) via
  :class:`OutputFormatter`.
  No HTTP, no auth — runs against a freshly-initialised AppState so
  the catalog is identical to what the live server would advertise.

The global ``--dry-run`` flag short-circuits BEFORE either transport is
booted; the ``run`` smoke contract from TASK-003 applies here too.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog
import typer
import uvicorn

from bsage.cli.commands._common import emit_dry_run, run_async
from bsage.core.config import get_settings
from bsage.mcp import plugin_bridge
from bsage.mcp.stdio import run_stdio_server

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

    from bsage.core.config import Settings
    from bsage.gateway.dependencies import AppState

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="mcp",
    help="MCP server transport launcher (stdio / http) and tool catalog.",
    no_args_is_help=True,
    add_completion=False,
)


def _build_app(settings: Settings) -> FastAPI:
    """Construct the FastAPI gateway — isolated so tests can patch it."""

    from bsage.gateway.app import create_app

    return create_app(settings)


def _build_state(settings: Settings) -> AppState:
    """Construct an AppState — isolated so ``list-tools`` tests can patch it."""

    from bsage.gateway.dependencies import AppState

    return AppState(settings)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@app.command("serve", help="Start the MCP server (stdio or http transport).")
def serve_cmd(
    ctx: typer.Context,
    transport: str = typer.Option(
        "stdio",
        "--transport",
        "-t",
        help="Transport: stdio (Claude Desktop) or http (gateway + /mcp).",
        case_sensitive=False,
    ),
    host: str | None = typer.Option(
        None,
        "--host",
        help="HTTP bind host (default: settings.gateway_host). Ignored for stdio.",
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        help="HTTP bind port (default: settings.gateway_port). Ignored for stdio.",
    ),
    log_level: str | None = typer.Option(
        None,
        "--log-level",
        help="HTTP log level (default: settings.log_level). Ignored for stdio.",
    ),
) -> None:
    transport_norm = transport.lower()
    if transport_norm not in {"stdio", "http"}:
        raise typer.BadParameter(f"--transport must be 'stdio' or 'http', got {transport!r}")

    settings = get_settings()
    plan: dict[str, Any] = {"command": "bsage mcp serve", "transport": transport_norm}

    if transport_norm == "http":
        plan["host"] = host or settings.gateway_host
        plan["port"] = port if port is not None else settings.gateway_port
        plan["log_level"] = log_level or settings.log_level

    cli_ctx = ctx.obj
    if bool(getattr(cli_ctx, "dry_run", False)):
        logger.info("bsage_mcp_serve_dry_run", **plan)
        emit_dry_run(cli_ctx, plan)
        return

    if transport_norm == "stdio":
        logger.info("bsage_mcp_serve_start", transport="stdio")
        asyncio.run(run_stdio_server())
        return

    logger.info("bsage_mcp_serve_start", **plan)
    fastapi_app = _build_app(settings)
    uvicorn.run(
        fastapi_app,
        host=plan["host"],
        port=plan["port"],
        log_level=plan["log_level"],
    )


# ---------------------------------------------------------------------------
# list-tools
# ---------------------------------------------------------------------------


@app.command("list-tools", help="List all MCP tools the server would advertise.")
def list_tools_cmd(ctx: typer.Context) -> None:
    cli_ctx = ctx.obj
    if bool(getattr(cli_ctx, "dry_run", False)):
        emit_dry_run(cli_ctx, {"command": "bsage mcp list-tools"})
        return

    settings = get_settings()
    state = _build_state(settings)

    # Tool *definitions* don't require an initialised AppState — registry
    # construction only reads ``settings.mcp_canon_mutation_enabled``
    # and the in-process module imports. We deliberately skip the
    # AppState lifespan so ``list-tools`` is fast, offline-friendly,
    # and never opens DB / vault / LLM connections.
    from bsage.mcp.server import build_registry

    registry = build_registry(state)

    async def _gather_plugin_tools() -> list[dict[str, Any]]:
        return list(await plugin_bridge.list_plugins_as_tools(state))

    rows: list[dict[str, Any]] = []
    for tool in sorted(registry.list_tools(), key=lambda t: t.name):
        spec = registry.get(tool.name)
        rows.append(
            {
                "name": tool.name,
                "description": tool.description,
                "required_permission": (spec.required_permission if spec else None),
                "audit_event": (spec.audit_event if spec else None),
            }
        )

    try:
        plugin_tools = run_async(_gather_plugin_tools)
    except Exception:  # noqa: BLE001 - plugin discovery is best-effort
        logger.warning("bsage_mcp_list_tools_plugin_bridge_failed", exc_info=True)
        plugin_tools = []
    for pt in plugin_tools:
        rows.append(
            {
                "name": pt["name"],
                "description": pt.get("description", ""),
                "required_permission": None,
                "audit_event": None,
            }
        )

    cli_ctx.formatter.emit(rows)


__all__ = ["app"]
