"""``bsage garden`` Typer sub-app — vault tree + (stub) maintenance.

Subcommands:

* ``list`` → ``GET /api/vault/tree`` — emit via :class:`OutputFormatter`.
* ``prune [--older-than DAYS]`` — *stub* (no REST surface yet). Mirrors
  the ``skills add/update/delete`` precedent: emits a planned-payload
  preview and exits 0; follow-up REVIEW promotes to live REST.
* ``recompile [--ids A,B,C]`` — *stub* (no REST surface yet).

``--dry-run`` short-circuits ``list`` BEFORE :func:`build_client` so
the HTTP layer is never reached when no profile URL is configured.
Stubs are inherently HTTP-free and emit unconditionally.
"""

from __future__ import annotations

from typing import Any

import structlog
import typer

from bsage.cli._client import build_client
from bsage.cli.commands._common import (
    emit_dry_run,
    emit_http_error,
    run_async,
)

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="garden",
    help="Inspect the vault tree and (stub) prune / recompile garden notes.",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List the vault tree (GET /api/vault/tree).")
def list_cmd(ctx: typer.Context) -> None:
    obj = ctx.obj
    path = "/api/vault/tree"
    if obj.dry_run:
        emit_dry_run(obj, {"method": "GET", "path": path})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.get(path)
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)

    obj.formatter.emit(resp.json() or [])


# ---------------------------------------------------------------------------
# prune / recompile — stubs (no REST surface yet)
# ---------------------------------------------------------------------------


def _stub_payload(action: str, **fields: Any) -> dict[str, Any]:
    return {
        "stub": True,
        "note": (
            f"`bsage garden {action}` has no REST endpoint yet. This is a "
            "planned-request preview; see follow-up REVIEW task."
        ),
        "action": action,
        **fields,
    }


@app.command(
    "prune",
    help="(stub) Preview the planned garden prune — no REST surface yet.",
)
def prune_cmd(
    ctx: typer.Context,
    older_than: int | None = typer.Option(
        None,
        "--older-than",
        help="Prune notes older than N days.",
    ),
) -> None:
    ctx.obj.formatter.emit(_stub_payload("prune", older_than_days=older_than))


@app.command(
    "recompile",
    help="(stub) Preview the planned garden recompile — no REST surface yet.",
)
def recompile_cmd(
    ctx: typer.Context,
    ids: str | None = typer.Option(
        None,
        "--ids",
        help="Comma-separated note ids to recompile (default: all).",
    ),
) -> None:
    parsed = [s.strip() for s in ids.split(",")] if ids else []
    parsed = [s for s in parsed if s]
    ctx.obj.formatter.emit(_stub_payload("recompile", ids=parsed))
