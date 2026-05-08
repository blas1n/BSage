"""``bsage ingest`` Typer sub-app — compile_batch ingestion control.

The ingest pipeline lives in :class:`bsage.garden.ingest_compiler.IngestCompiler`
(``compile_batch``). The current Gateway exposes *no* ``/api/ingest/...``
or ``/api/compile_batch`` REST surface — ingestion is driven in-process
by ``AgentLoop.on_input`` after a webhook fires. So both subcommands ship
as planned-payload stubs (mirroring the ``skills add/update/delete``
pattern from TASK-004): they emit a machine-readable request preview via
the formatter and exit 0. A follow-up REVIEW task tracks promoting them
to live REST once the endpoint lands.

Stubs do not need ``--dry-run`` checks — they are inherently HTTP-free.
"""

from __future__ import annotations

from typing import Any

import typer

app = typer.Typer(
    name="ingest",
    help="Trigger compile_batch ingestion and inspect status (stubs — no REST yet).",
    no_args_is_help=True,
    add_completion=False,
)


def _stub_payload(action: str, **fields: Any) -> dict[str, Any]:
    return {
        "stub": True,
        "note": (
            f"`bsage ingest {action}` has no REST endpoint yet — "
            "compile_batch runs in-process via AgentLoop. This is a "
            "planned-request preview; see follow-up REVIEW task."
        ),
        "action": action,
        **fields,
    }


@app.command(
    "run",
    help="(stub) Preview the planned compile_batch run — no REST surface yet.",
)
def run_cmd(
    ctx: typer.Context,
    source: str | None = typer.Option(
        None,
        "--source",
        help="Source path (seed directory) to ingest.",
    ),
) -> None:
    ctx.obj.formatter.emit(_stub_payload("run", source=source))


@app.command(
    "status",
    help="(stub) Preview the planned compile_batch status query — no REST yet.",
)
def status_cmd(
    ctx: typer.Context,
    task: str | None = typer.Option(
        None,
        "--task",
        help="Specific compile_batch task ID to inspect.",
    ),
) -> None:
    ctx.obj.formatter.emit(_stub_payload("status", task=task))
