"""Tests for bsage.core.exceptions — domain exception hierarchy."""

from bsage.core.exceptions import (
    BSageError,
    ConnectorAuthError,
    ConnectorNotFoundError,
    SafeModeError,
    SkillLoadError,
    SkillRejectedError,
    SkillRunError,
    VaultPathError,
)


class TestExceptionHierarchy:
    """All domain exceptions inherit from BSageError."""

    def test_bsage_error_is_base(self) -> None:
        err = BSageError("base error")
        assert isinstance(err, Exception)
        assert str(err) == "base error"

    def test_skill_load_error(self) -> None:
        err = SkillLoadError("missing skill.yaml")
        assert isinstance(err, BSageError)
        assert "missing skill.yaml" in str(err)

    def test_skill_run_error(self) -> None:
        err = SkillRunError("execution failed")
        assert isinstance(err, BSageError)

    def test_skill_rejected_error(self) -> None:
        err = SkillRejectedError("user rejected garden-writer")
        assert isinstance(err, BSageError)
        assert "garden-writer" in str(err)

    def test_connector_not_found_error(self) -> None:
        err = ConnectorNotFoundError("google-calendar")
        assert isinstance(err, BSageError)

    def test_connector_auth_error(self) -> None:
        err = ConnectorAuthError("Authentication failed. Check credentials in .credentials/")
        assert isinstance(err, BSageError)
        # Must not expose secrets in message
        assert "token" not in str(err).lower()
        assert "key" not in str(err).lower()

    def test_vault_path_error(self) -> None:
        err = VaultPathError("path traversal detected")
        assert isinstance(err, BSageError)

    def test_safe_mode_error(self) -> None:
        err = SafeModeError("safe mode system failure")
        assert isinstance(err, BSageError)

    def test_all_exceptions_catchable_as_bsage_error(self) -> None:
        """Catching BSageError should catch all domain exceptions."""
        exceptions = [
            SkillLoadError("test"),
            SkillRunError("test"),
            SkillRejectedError("test"),
            ConnectorNotFoundError("test"),
            ConnectorAuthError("test"),
            VaultPathError("test"),
            SafeModeError("test"),
        ]
        for exc in exceptions:
            try:
                raise exc
            except BSageError:
                pass  # Should be caught
