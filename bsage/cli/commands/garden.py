"""``bsage garden`` Typer sub-app — vault tree listing.

Subcommands:

* ``list`` → ``GET /api/vault/tree`` — emit via :class:`OutputFormatter`.

Mutation operations (``prune`` / ``recompile``) are intentionally absent.
REVIEW-005A resolved the planned-payload stubs that earlier shipped under
TASK-005: the BSage Gateway has no REST surface for vault prune /
recompile today, and exposing one prematurely would let any caller with a
valid token destructively mutate vault state. When operators need to
prune or recompile they invoke the in-process pipelines via the running
``bsage`` daemon (``compile_batch`` runs through
:class:`bsage.garden.ingest_compiler.IngestCompiler`; reindex /prune live
in :mod:`bsage.garden.migrations` + :class:`~bsage.garden.vault.Vault`).
A future task will add the REST endpoints together with the CLI commands
that wrap them — paired, never decoupled.

``--dry-run`` short-circuits ``list`` BEFORE :func:`build_client` so the
HTTP layer is never reached when no profile URL is configured.
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
    help="Inspect the vault tree (mutation ops are git/in-process only).",
    no_args_is_help=True,
    add_completion=False,
)


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
