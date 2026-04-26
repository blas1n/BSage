"""Structured logging configuration — delegates to bsvibe_core.

Phase A migration (2026-04-26): the structlog setup pipeline now lives in
``bsvibe_core.configure_logging``. This module keeps the BSage-specific
positional signature (``configure_logging(log_level)``) so existing call
sites in ``bsage.cli`` / ``bsage.gateway.app`` and the
``test_logging.py`` regression suite migrate without churn, and forwards
to the shared implementation with ``service_name="bsage"`` for log fan-in.
"""

from __future__ import annotations

from bsvibe_core import configure_logging as _configure_logging_core


def configure_logging(log_level: str = "info") -> None:
    """Configure structlog with JSON output, timestamps, and log level.

    Thin wrapper over :func:`bsvibe_core.configure_logging` that pins
    ``service_name="bsage"`` so every log line is taggable in the audit
    pipeline. The positional ``log_level`` argument is preserved for
    backward compatibility with existing call sites.
    """
    _configure_logging_core(level=log_level, service_name="bsage")
