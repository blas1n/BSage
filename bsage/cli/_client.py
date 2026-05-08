"""HTTP-client construction for ``bsage`` sub-apps.

Sub-apps (``skills``, ``plugins``, ``ingest``, ``garden``, ``canon``,
``settings``) build a :class:`~bsvibe_cli_base.http.CliHttpClient` from
the resolved :class:`~bsvibe_cli_base.cli.CliContext` so they all share
401-refresh-retry semantics and profile-derived headers.

This wrapper exists so subcommands don't reach into ``ctx.obj`` and
re-implement the same construction; tests can mock ``build_client``
once and stub HTTP for every sub-app.
"""

from __future__ import annotations

import typer
from bsvibe_cli_base import CliHttpClient
from bsvibe_cli_base.cli import CliContext


def build_client(ctx: CliContext, *, timeout_s: float = 10.0) -> CliHttpClient:
    """Construct a ``CliHttpClient`` from a resolved ``CliContext``.

    Raises
    ------
    typer.BadParameter
        When ``ctx.url`` is empty — surfaces the missing-profile case as
        a user-facing error instead of a confusing httpx connect error.
    """

    if not ctx.url:
        msg = (
            "No control-plane URL resolved. Pass --url, set BSVIBE_URL, or "
            "configure an active profile (`bsage profile add`)."
        )
        raise typer.BadParameter(msg)

    headers: dict[str, str] = {}
    if ctx.tenant_id:
        headers["X-Tenant-ID"] = ctx.tenant_id

    return CliHttpClient(
        base_url=ctx.url,
        token=ctx.token,
        timeout_s=timeout_s,
        headers=headers or None,
    )


__all__ = ["build_client"]
