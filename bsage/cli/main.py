"""``bsage`` Typer CLI root — global flags wired via ``cli_app``.

This module exposes the ``app`` object that the ``bsage`` console
script entry point resolves to. Sub-apps land here in TASK-003..007:

* ``bsage run``      — server boot (TASK-003)
* ``bsage skills``   — skills CRUD + run (TASK-004)
* ``bsage plugins``  — plugin install / enable / disable (TASK-004)
* ``bsage ingest``   — compile_batch ingest (TASK-005)
* ``bsage garden``   — garden list / prune / recompile (TASK-005)
* ``bsage canon``    — canonicalization slices 1-6 (TASK-005)
* ``bsage settings`` — RuntimeConfig get / set (TASK-006)

The factory :func:`bsvibe_cli_base.cli_app` already wires the standard
global flag set (``--profile``, ``--output``, ``--tenant``, ``--token``,
``--url``, ``--dry-run``) onto the root callback, so subcommands receive
a fully-resolved :class:`~bsvibe_cli_base.cli.CliContext` on
``ctx.obj``.
"""

from __future__ import annotations

from bsvibe_cli_base import cli_app

app = cli_app(
    name="bsage",
    help="BSage — Personal AI Agent control plane CLI.",
)


__all__ = ["app"]
