"""``bsage run`` Typer command — server boot.

Phase 4 retires the threaded ``uvicorn.Server`` + ``ChatBridge`` REPL
"mount trick" the legacy Click CLI used. This rewrite is a clean
``uvicorn.run(create_app(...))`` hand-off:

* No background thread, no health-poll, no in-process REPL — those
  responsibilities move to a dedicated ``bsage chat`` sub-app later.
* ``--host`` / ``--port`` / ``--log-level`` / ``--reload`` honour the
  same env-derived defaults as the legacy command (deploy scripts that
  pass these flags continue to work unchanged).
* The global ``--dry-run`` flag from :func:`bsvibe_cli_base.cli_app`
  short-circuits BEFORE :func:`_build_app` so the FastAPI app is never
  constructed and no port is bound. This is the smoke contract from
  TASK-003 acceptance ("returns 0 without binding port").

The module deliberately does not import :mod:`bsage.gateway.app` at
module load time — the import path runs through :func:`_build_app`
inside the command body so tests can patch it cleanly and the dry-run
path skips the full app graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
import typer
import uvicorn

from bsage.core.config import get_settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

    from bsage.core.config import Settings

logger = structlog.get_logger(__name__)


def _build_app(settings: Settings) -> FastAPI:
    """Construct the FastAPI app — isolated so tests can patch it
    without touching :mod:`bsage.gateway.app` directly."""

    from bsage.gateway.app import create_app

    return create_app(settings)


def register(parent: typer.Typer) -> None:
    """Attach the ``run`` command to ``parent``.

    Single-command modules use ``register(parent)`` rather than building
    a sub-app, since ``run`` is a top-level command not a group.
    """

    @parent.command(
        "run",
        help=(
            "Start the BSage Gateway HTTP server (uvicorn). "
            "Hands off directly to uvicorn — no in-process chat REPL."
        ),
    )
    def run_command(  # noqa: PLR0913 — flag surface mirrors uvicorn's own options
        ctx: typer.Context,
        host: str | None = typer.Option(
            None,
            "--host",
            help="Bind host (default: settings.gateway_host).",
        ),
        port: int | None = typer.Option(
            None,
            "--port",
            help="Bind port (default: settings.gateway_port).",
        ),
        log_level: str | None = typer.Option(
            None,
            "--log-level",
            help="uvicorn log level (default: settings.log_level).",
        ),
        reload: bool = typer.Option(
            False,
            "--reload",
            help="Enable uvicorn auto-reload (development only).",
        ),
    ) -> None:
        settings = get_settings()
        resolved_host = host or settings.gateway_host
        resolved_port = port if port is not None else settings.gateway_port
        resolved_log_level = log_level or settings.log_level

        plan: dict[str, Any] = {
            "command": "bsage run",
            "host": resolved_host,
            "port": resolved_port,
            "log_level": resolved_log_level,
            "reload": reload,
        }

        cli_ctx = ctx.obj
        dry_run = bool(getattr(cli_ctx, "dry_run", False))

        if dry_run:
            logger.info("bsage_run_dry_run", **plan)
            if cli_ctx is not None and getattr(cli_ctx, "formatter", None) is not None:
                cli_ctx.formatter.emit({"dry_run": True, **plan})
            else:  # pragma: no cover - cli_app always supplies a formatter
                typer.echo(str({"dry_run": True, **plan}))
            return

        logger.info("bsage_run_start", **plan)
        app = _build_app(settings)
        uvicorn.run(
            app,
            host=resolved_host,
            port=resolved_port,
            log_level=resolved_log_level,
            reload=reload,
        )


__all__ = ["register"]
