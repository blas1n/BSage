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

import sys

import structlog
from bsvibe_cli_base import cli_app

from bsage.cli.commands import run as run_cmd
from bsage.cli.commands.canon import app as canon_app
from bsage.cli.commands.garden import app as garden_app
from bsage.cli.commands.ingest import app as ingest_app
from bsage.cli.commands.plugins import app as plugins_app
from bsage.cli.commands.settings import app as settings_app
from bsage.cli.commands.skills import app as skills_app

# Route structlog to stderr so subcommands keep stdout clean for the
# OutputFormatter (JSON / YAML / TSV / table) — operators piping output
# through ``jq`` shouldn't see log lines mixed into the data stream.
structlog.configure(
    processors=structlog.get_config()["processors"],
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)

app = cli_app(
    name="bsage",
    help="BSage — Personal AI Agent control plane CLI.",
)

run_cmd.register(app)
app.add_typer(skills_app, name="skills")
app.add_typer(plugins_app, name="plugins")
app.add_typer(ingest_app, name="ingest")
app.add_typer(garden_app, name="garden")
app.add_typer(canon_app, name="canon")
app.add_typer(settings_app, name="settings")


__all__ = ["app"]
