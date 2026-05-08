"""``bsage settings`` Typer sub-app — RuntimeConfig get/set.

Subcommands:

* ``get [KEY] [--list]`` → ``GET /api/config``. Without ``KEY`` (and
  without ``--list``) emits the full snapshot dict. With ``KEY``, emits
  ``{KEY: value}`` for that single field. With ``--list``, emits a list
  of ``{"key": ..., "value": ...}`` rows for table-friendly output.
* ``set KEY VALUE`` → ``PATCH /api/config`` with ``{KEY: parsed_value}``.
  ``VALUE`` is parsed as a JSON literal (``true``/``42``/``["a","b"]``)
  and falls back to a raw string when JSON decode fails.

Unknown ``KEY`` (not in the :class:`bsage.gateway.routes.ConfigUpdate`
field set for ``set``, not in the snapshot for ``get``) raises
:class:`typer.BadParameter` so misspellings surface before any HTTP
call. ``--dry-run`` short-circuits BEFORE :func:`build_client` so the
HTTP layer is never reached without a configured profile URL.

Secret values (``llm_api_key`` / ``embedding_api_key``) are NEVER
logged — :func:`set_cmd` logs only the field name, never the value.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
import typer

from bsage.cli._client import build_client
from bsage.cli.commands._common import (
    emit_dry_run,
    emit_http_error,
    run_async,
)
from bsage.gateway.routes import ConfigUpdate

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="settings",
    help="Get or set RuntimeConfig fields via /api/config.",
    no_args_is_help=True,
    add_completion=False,
)

_CONFIG_PATH = "/api/config"
_VALID_SET_KEYS: frozenset[str] = frozenset(ConfigUpdate.model_fields.keys())
_SECRET_KEYS: frozenset[str] = frozenset({"llm_api_key", "embedding_api_key"})


def _parse_value(raw: str) -> Any:
    """Parse VALUE as JSON, falling back to raw string on decode error."""

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@app.command("get", help="Read the runtime config — all keys, one key, or as a list.")
def get_cmd(
    ctx: typer.Context,
    key: str | None = typer.Argument(None, help="Optional config key to read."),
    list_all: bool = typer.Option(
        False,
        "--list",
        help="Emit every config key as a list of {key, value} rows.",
    ),
) -> None:
    obj = ctx.obj
    if key is not None and list_all:
        raise typer.BadParameter("--list is mutually exclusive with KEY")

    if obj.dry_run:
        emit_dry_run(obj, {"method": "GET", "path": _CONFIG_PATH})
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.get(_CONFIG_PATH)
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)

    snapshot = resp.json() or {}
    if not isinstance(snapshot, dict):
        obj.formatter.emit(snapshot)
        return

    if key is not None:
        if key not in snapshot:
            typer.echo(
                f"Error: unknown config key {key!r}. "
                f"Run 'bsage settings get --list' to see available keys.",
                err=True,
            )
            raise typer.Exit(code=1)
        obj.formatter.emit({key: snapshot[key]})
        return

    if list_all:
        rows = [{"key": k, "value": v} for k, v in sorted(snapshot.items())]
        obj.formatter.emit(rows)
        return

    obj.formatter.emit(snapshot)


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------


@app.command("set", help="Update a single runtime config key (PATCH /api/config).")
def set_cmd(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Config key to update."),
    value: str = typer.Argument(
        ...,
        help="Value — parsed as a JSON literal, falls back to raw string.",
    ),
) -> None:
    obj = ctx.obj
    if key not in _VALID_SET_KEYS:
        raise typer.BadParameter(
            f"Unknown config key {key!r}. Valid keys: {sorted(_VALID_SET_KEYS)}"
        )

    parsed = _parse_value(value)
    body = {key: parsed}

    if obj.dry_run:
        emit_dry_run(obj, {"method": "PATCH", "path": _CONFIG_PATH, "body": body})
        return

    # Never log the value — secret fields would leak into structlog
    # otherwise. Operators read response output for confirmation; the
    # log line is for audit-of-intent only.
    logger.info("bsage_settings_set", key=key)

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.request("PATCH", _CONFIG_PATH, json=body)
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)

    obj.formatter.emit(resp.json())
