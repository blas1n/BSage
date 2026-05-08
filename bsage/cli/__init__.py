"""BSage Typer CLI package — Phase 4 rewrite.

The new ``bsage`` CLI is built on ``bsvibe-cli-base`` so it shares
``ProfileStore`` / ``OutputFormatter`` / ``CliHttpClient`` with every
other BSVibe product CLI.

Sub-apps (``run``, ``skills``, ``plugins``, ``ingest``, ``garden``,
``canon``, ``settings``) are mounted in :mod:`bsage.cli.main`. The
script entry point ``bsage`` (defined in ``pyproject.toml``) resolves
to ``bsage.cli.main:app``.
"""

from __future__ import annotations

__all__: list[str] = []
