"""``bsage plugins`` Typer sub-app — plugin registry + dependency install.

Subcommands:

* ``list`` → ``GET /api/plugins`` — emit via :class:`OutputFormatter`.
* ``install NAME`` — in-process ``uv pip install -r <plugins_dir>/<name>/
  requirements.txt``. Honours ``--dry-run`` by skipping the subprocess
  and emitting a planned-payload.
* ``enable NAME`` / ``disable NAME`` — *idempotent* wrappers around the
  toggle endpoint. Because ``POST /api/entries/{name}/toggle`` is a flip
  (not an absolute set), the command first probes ``GET /api/plugins``
  + ``/api/skills`` to learn the current ``enabled`` state. If the entry
  is already in the target state we emit a no-op result and skip the
  toggle so running ``enable`` twice never silently re-disables.
"""

from __future__ import annotations

import subprocess
from typing import Any

import structlog
import typer

from bsage.cli._client import build_client
from bsage.cli.commands._common import (
    emit_dry_run,
    emit_http_error,
    run_async,
    validate_entry_name,
)
from bsage.core.config import get_settings

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="plugins",
    help="List plugins, install plugin dependencies, enable / disable entries.",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List all loaded plugins (code-based entries).")
def list_cmd(ctx: typer.Context) -> None:
    obj = ctx.obj
    path = "/api/plugins"
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
# install
# ---------------------------------------------------------------------------


@app.command(
    "install",
    help="Install a plugin's dependencies (uv pip install -r requirements.txt).",
)
def install_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Plugin directory name."),
) -> None:
    obj = ctx.obj
    validate_entry_name(name)

    settings = get_settings()
    plugin_dir = settings.plugins_dir / name
    if not plugin_dir.is_dir():
        typer.echo(f"Error: plugin directory not found: {plugin_dir}", err=True)
        raise typer.Exit(code=1)

    req_file = plugin_dir / "requirements.txt"
    if not req_file.exists():
        obj.formatter.emit({"name": name, "installed": False, "reason": "no requirements.txt"})
        return

    cmd = ["uv", "pip", "install", "-r", str(req_file)]
    if obj.dry_run:
        emit_dry_run(obj, {"name": name, "command": cmd})
        return

    logger.info("bsage_plugins_install", name=name)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        typer.echo(
            f"Error: dependency install failed for {name!r}\n{result.stderr}".rstrip(),
            err=True,
        )
        raise typer.Exit(code=1)

    obj.formatter.emit({"name": name, "installed": True, "requirements": str(req_file)})


# ---------------------------------------------------------------------------
# enable / disable
# ---------------------------------------------------------------------------


async def _fetch_entry_state(client: Any, name: str) -> dict[str, Any] | None:
    """Probe ``/api/plugins`` then ``/api/skills`` for ``name``."""

    for path in ("/api/plugins", "/api/skills"):
        resp = await client.get(path)
        if resp.status_code >= 400:
            emit_http_error(resp)
            raise typer.Exit(code=1)
        rows = resp.json() or []
        match = next((row for row in rows if row.get("name") == name), None)
        if match is not None:
            return match
    return None


async def _ensure_state(ctx_obj: Any, name: str, want_enabled: bool) -> dict[str, Any]:
    client = build_client(ctx_obj)
    try:
        entry = await _fetch_entry_state(client, name)
        if entry is None:
            typer.echo(f"Error: entry not found: {name}", err=True)
            raise typer.Exit(code=1)

        if bool(entry.get("enabled")) == want_enabled:
            return {"name": name, "enabled": want_enabled, "changed": False}

        resp = await client.post(f"/api/entries/{name}/toggle")
        if resp.status_code >= 400:
            emit_http_error(resp)
            raise typer.Exit(code=1)
        body = resp.json() or {}
        return {
            "name": name,
            "enabled": bool(body.get("enabled", want_enabled)),
            "changed": True,
        }
    finally:
        await client.aclose()


def _toggle_command(want_enabled: bool, action: str) -> Any:
    def _cmd(
        ctx: typer.Context,
        name: str = typer.Argument(..., help="Plugin or skill name."),
    ) -> None:
        obj = ctx.obj
        validate_entry_name(name)
        path = f"/api/entries/{name}/toggle"
        if obj.dry_run:
            emit_dry_run(
                obj,
                {
                    "method": "POST",
                    "path": path,
                    "ensure_enabled": want_enabled,
                    "name": name,
                },
            )
            return
        logger.info("bsage_plugins_toggle", name=name, action=action)
        result = run_async(lambda: _ensure_state(obj, name, want_enabled))
        obj.formatter.emit(result)

    return _cmd


app.command("enable", help="Ensure a plugin/skill is enabled (idempotent).")(
    _toggle_command(True, "enable")
)
app.command("disable", help="Ensure a plugin/skill is disabled (idempotent).")(
    _toggle_command(False, "disable")
)
