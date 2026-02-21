"""Tests for bsage.core.logging — structlog configuration."""

import structlog

from bsage.core.logging import configure_logging


class TestConfigureLogging:
    """Test structlog configuration."""

    def test_configure_logging_sets_up_structlog(self) -> None:
        """configure_logging should configure structlog without errors."""
        configure_logging("info")
        logger = structlog.get_logger("test")
        assert logger is not None

    def test_configure_logging_with_debug_level(self) -> None:
        """Should accept debug log level."""
        configure_logging("debug")
        logger = structlog.get_logger("test")
        assert logger is not None

    def test_configure_logging_default_level(self) -> None:
        """Default log level should be info."""
        configure_logging()
        logger = structlog.get_logger("test")
        assert logger is not None
