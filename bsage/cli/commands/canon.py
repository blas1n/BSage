"""``bsage canon`` Typer sub-app — canonicalization slices 1-6.

All four subcommands wrap routes mounted under ``/api/canonicalization``
by :func:`bsage.gateway.canonicalization_routes.create_canonicalization_router`.

* ``list [--kind {concepts|proposals|actions|policies}]`` — concepts is
  the default. ``policies`` maps to ``policies/active``.
* ``draft KIND --params JSON [--slug X] [--source-proposal PATH]`` →
  ``POST /actions/draft``.
* ``apply ACTION_PATH [--mode {apply|approve|reject}] [--reason TEXT]`` →
  ``POST /actions/{apply|approve|reject}``. ``--reason`` is forwarded
  on ``reject`` only.
* ``status [--path PATH]`` — note read when ``--path`` is given,
  otherwise the action list.

``--dry-run`` short-circuits BEFORE :func:`build_client` for every
HTTP-backed command so the layer is never reached without a profile.
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
)

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="canon",
    help="Canonicalization: list concepts/proposals/actions, draft + apply actions.",
    no_args_is_help=True,
    add_completion=False,
)


_LIST_KIND_TO_PATH = {
    "concepts": "/api/canonicalization/concepts",
    "proposals": "/api/canonicalization/proposals",
    "actions": "/api/canonicalization/actions",
    "policies": "/api/canonicalization/policies/active",
}

_APPLY_MODE_TO_SUFFIX = {
    "apply": "apply",
    "approve": "approve",
    "reject": "reject",
}


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command("list", help="List canonicalization entries by kind.")
def list_cmd(
    ctx: typer.Context,
    kind: str = typer.Option(
        "concepts",
        "--kind",
        help="One of: concepts, proposals, actions, policies.",
    ),
) -> None:
    obj = ctx.obj
    if kind not in _LIST_KIND_TO_PATH:
        raise typer.BadParameter(
            f"--kind must be one of {sorted(_LIST_KIND_TO_PATH)} (got {kind!r})"
        )
    path = _LIST_KIND_TO_PATH[kind]

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

    payload = resp.json() or {}
    items = payload.get("items", payload) if isinstance(payload, dict) else payload
    obj.formatter.emit(items or [])


# ---------------------------------------------------------------------------
# draft
# ---------------------------------------------------------------------------


@app.command("draft", help="Draft a canonicalization action (POST /actions/draft).")
def draft_cmd(
    ctx: typer.Context,
    kind: str = typer.Argument(..., help="Action kind (e.g. merge, split, deprecate)."),
    params_json: str = typer.Option(
        ...,
        "--params",
        help="JSON object passed as the action parameters.",
    ),
    slug: str | None = typer.Option(
        None,
        "--slug",
        help="Optional human-readable slug for the action filename.",
    ),
    source_proposal: str | None = typer.Option(
        None,
        "--source-proposal",
        "--source",
        help="Path of the proposal that motivated this draft.",
    ),
) -> None:
    obj = ctx.obj
    decoded = parse_json_body(params_json, "--params")
    if not isinstance(decoded, dict):
        raise typer.BadParameter("--params must decode to a JSON object")

    body: dict[str, Any] = {"kind": kind, "params": decoded}
    if slug is not None:
        body["slug"] = slug
    if source_proposal is not None:
        body["source_proposal"] = source_proposal

    path = "/api/canonicalization/actions/draft"
    if obj.dry_run:
        emit_dry_run(obj, {"method": "POST", "path": path, "body": body})
        return

    logger.info("bsage_canon_draft", kind=kind, slug=slug)

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
# apply
# ---------------------------------------------------------------------------


@app.command(
    "apply",
    help="Apply / approve / reject a canonicalization action (POST /actions/<mode>).",
)
def apply_cmd(
    ctx: typer.Context,
    action_path: str = typer.Argument(..., help="Path of the action note."),
    mode: str = typer.Option(
        "apply",
        "--mode",
        help="One of: apply, approve, reject.",
    ),
    reason: str | None = typer.Option(
        None,
        "--reason",
        help="Required for --mode reject; optional otherwise.",
    ),
) -> None:
    obj = ctx.obj
    if mode not in _APPLY_MODE_TO_SUFFIX:
        raise typer.BadParameter(
            f"--mode must be one of {sorted(_APPLY_MODE_TO_SUFFIX)} (got {mode!r})"
        )
    suffix = _APPLY_MODE_TO_SUFFIX[mode]
    path = f"/api/canonicalization/actions/{suffix}"

    body: dict[str, Any] = {"action_path": action_path}
    if mode == "reject" and reason is not None:
        body["reason"] = reason

    if obj.dry_run:
        emit_dry_run(obj, {"method": "POST", "path": path, "body": body})
        return

    logger.info("bsage_canon_apply", mode=mode, action_path=action_path)

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
# status
# ---------------------------------------------------------------------------


@app.command(
    "status",
    help="Show canonicalization status — note when --path is set, action list otherwise.",
)
def status_cmd(
    ctx: typer.Context,
    path: str | None = typer.Option(
        None,
        "--path",
        help="Action/proposal/concept note path; reads /note?path=... when set.",
    ),
) -> None:
    obj = ctx.obj
    if path is not None:
        endpoint = "/api/canonicalization/note"
        request_kwargs: dict[str, Any] = {"params": {"path": path}}
    else:
        endpoint = "/api/canonicalization/actions"
        request_kwargs = {}

    if obj.dry_run:
        plan: dict[str, Any] = {"method": "GET", "path": endpoint}
        if request_kwargs:
            plan["params"] = request_kwargs.get("params")
        emit_dry_run(obj, plan)
        return

    async def _go() -> Any:
        client = build_client(obj)
        try:
            return await client.get(endpoint, **request_kwargs)
        finally:
            await client.aclose()

    resp = run_async(_go)
    if resp.status_code >= 400:
        emit_http_error(resp)
        raise typer.Exit(code=1)

    payload = resp.json()
    if isinstance(payload, dict) and "items" in payload and path is None:
        obj.formatter.emit(payload["items"] or [])
    else:
        obj.formatter.emit(payload)
