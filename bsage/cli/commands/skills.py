"""``bsage skills`` Typer sub-app — wraps the skills REST surface.

Subcommands:

* ``list`` → ``GET  /api/skills`` — emit via :class:`OutputFormatter`.
* ``run NAME [--input JSON]`` → ``POST /api/run/{name}`` with the JSON
  body as ``context.input_data``.
* ``add NAME --from-file PATH`` / ``update NAME --from-file PATH`` /
  ``delete NAME`` — *stubs*. Skills are file-backed (yaml + markdown)
  and there is no REST surface for these mutations yet
  (see ``.agent/cli-inventory.md`` and the follow-up REVIEW task). They
  emit a planned-payload via the formatter and exit 0 so AI agents and
  operators get a machine-readable preview of the would-be request.

``--dry-run`` short-circuits BEFORE :func:`build_client` for the live
commands so the HTTP layer is never reached when no profile URL is
configured.
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
    help="List, run, and (stub) add/update/delete skills.",
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


# ---------------------------------------------------------------------------
# add / update / delete — stubs (no REST surface yet)
# ---------------------------------------------------------------------------


def _stub_payload(name: str, action: str, source: str | None) -> dict[str, Any]:
    return {
        "stub": True,
        "note": (
            f"`bsage skills {action}` has no REST endpoint yet — skills are "
            "file-backed (yaml+markdown). This is a planned-request preview; "
            "see follow-up REVIEW task."
        ),
        "name": name,
        "action": action,
        "source": source,
    }


@app.command(
    "add",
    help="(stub) Preview the planned add-skill request — no REST surface yet.",
)
def add_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Skill name."),
    from_file: str | None = typer.Option(
        None,
        "--from-file",
        help="Path to the skill .md (yaml frontmatter + markdown body).",
    ),
) -> None:
    validate_entry_name(name)
    ctx.obj.formatter.emit(_stub_payload(name, "add", from_file))


@app.command(
    "update",
    help="(stub) Preview the planned update-skill request — no REST surface yet.",
)
def update_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Skill name."),
    from_file: str | None = typer.Option(
        None,
        "--from-file",
        help="Path to the updated skill .md.",
    ),
) -> None:
    validate_entry_name(name)
    ctx.obj.formatter.emit(_stub_payload(name, "update", from_file))


@app.command(
    "delete",
    help="(stub) Preview the planned delete-skill request — no REST surface yet.",
)
def delete_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Skill name."),
) -> None:
    validate_entry_name(name)
    ctx.obj.formatter.emit(_stub_payload(name, "delete", None))
