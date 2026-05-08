"""Shared helpers for ``bsage`` CLI sub-apps.

Centralises a small set of primitives every HTTP-backed sub-app needs:

* :func:`emit_dry_run`  — render the planned request via the formatter
  *before* :func:`bsage.cli._client.build_client` is called, so the
  ``--dry-run`` smoke path is HTTP-free (and works without a configured
  profile URL).
* :func:`emit_http_error` — print a one-line ``Error: HTTP <code> — <detail>``
  to stderr; never leaks a stack trace into operator-facing output.
* :func:`run_async` — run an ``async`` coroutine factory under
  ``asyncio.run`` so subcommands stay sync-style while ``CliHttpClient``
  remains async-only.
* :func:`validate_entry_name` — enforce the same lowercase-with-hyphens
  pattern used by Plugin/Skill loaders.

The helpers mirror the ``bsgateway`` precedent (PR #43) so both CLIs
have the same dry-run / error / name-validation shape.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import typer

__all__ = [
    "emit_dry_run",
    "emit_http_error",
    "parse_json_body",
    "run_async",
    "validate_entry_name",
]


_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def emit_dry_run(ctx_obj: Any, payload: dict[str, Any]) -> None:
    """Render the planned request without firing it."""

    ctx_obj.formatter.emit({"dry_run": True, **payload})


def emit_http_error(resp: Any) -> None:
    """Print a one-line error to stderr — no stack trace."""

    detail: Any
    try:
        body = resp.json()
    except Exception:
        body = None
    if isinstance(body, dict) and "detail" in body:
        detail = body["detail"]
    elif body is not None:
        detail = body
    else:
        detail = (resp.text or "").strip()[:300]
    typer.echo(f"Error: HTTP {resp.status_code} — {detail}", err=True)


def parse_json_body(raw: str, flag: str) -> Any:
    """Decode ``raw`` as JSON; surface decode errors as ``BadParameter``."""

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"{flag} is not valid JSON: {exc}") from exc


def run_async(coro_factory: Callable[[], Awaitable[Any]]) -> Any:
    """Run an async coroutine factory (lets sub-apps stay sync)."""

    return asyncio.run(coro_factory())


def validate_entry_name(name: str) -> str:
    """Validate Plugin/Skill name — lowercase alphanumeric + hyphens."""

    if not _NAME_RE.match(name):
        raise typer.BadParameter(
            f"Invalid name: {name!r}. Use lowercase alphanumeric with hyphens "
            "(pattern: [a-z][a-z0-9-]*)."
        )
    return name
