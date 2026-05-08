"""``bsage skills`` Typer sub-app — wraps the skills REST surface.

Subcommands:

* ``list`` → ``GET  /api/skills`` — emit via :class:`OutputFormatter`.
* ``run NAME [--input JSON]`` → ``POST /api/run/{name}`` with the JSON
  body as ``context.input_data``.

There are intentionally no ``add``/``update``/``delete`` commands.
Skills are file-backed YAML+Markdown under ``skills/`` and authored via
git — that's the project's contract (see ``.claude/rules/skill-system``).
A REST mutation surface would let any caller register an arbitrary LLM
system prompt that the agent then executes, which is a prompt-injection
vector for a personal control plane. REVIEW-004A removed the earlier
planned-payload stubs once that authoring boundary was confirmed.

``--dry-run`` short-circuits BEFORE :func:`build_client` so the HTTP
layer is never reached when no profile URL is configured.
"""

from __future__ import annotations

from typing import Any

import structlog
import typer

from bsage.cli._client import build_client
from bsage.cli.commands._common import (
    emit_dry_run,
    emit_http_error,
    parse_json_body,
    run_async,
    validate_entry_name,
)

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="skills",
    help="List and run skills (authoring is git-based under skills/).",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List all loaded skills (LLM-based entries).")
def list_cmd(ctx: typer.Context) -> None:
    obj = ctx.obj
    path = "/api/skills"
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
# run
# ---------------------------------------------------------------------------


@app.command("run", help="Run a skill by name (POST /api/run/{name}).")
def run_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Skill name (lowercase + hyphens)."),
    input_json: str | None = typer.Option(
        None,
        "--input",
        help="JSON object passed as the skill's input_data.",
    ),
) -> None:
    obj = ctx.obj
    validate_entry_name(name)
    body: dict[str, Any] = {}
    if input_json is not None:
        decoded = parse_json_body(input_json, "--input")
        if not isinstance(decoded, dict):
            raise typer.BadParameter("--input must decode to a JSON object")
        body = decoded

    path = f"/api/run/{name}"
    if obj.dry_run:
        emit_dry_run(obj, {"method": "POST", "path": path, "body": body})
        return

    logger.info("bsage_skills_run", name=name)

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.post(path, json=body)
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)

    obj.formatter.emit(resp.json())
