"""Sub-commands for the ``bsage`` Typer CLI.

Every module here exposes either:

* a single ``register(app: typer.Typer) -> None`` entry point that
  attaches one or more commands to the parent app (used for top-level
  commands like ``bsage run``); or
* a ``app: typer.Typer`` sub-app instance that the parent mounts via
  :meth:`typer.Typer.add_typer` (used for command groups like
  ``bsage skills``).
"""

from __future__ import annotations

__all__: list[str] = []
