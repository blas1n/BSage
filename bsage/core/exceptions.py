"""Domain exception hierarchy for BSage."""


class BSageError(Exception):
    """Base exception for all BSage domain errors."""


class SkillLoadError(BSageError):
    """Raised when a skill fails to load (missing yaml, invalid fields)."""


class SkillRunError(BSageError):
    """Raised when a skill fails during execution."""


class SkillRejectedError(BSageError):
    """Raised when SafeModeGuard rejects a dangerous skill."""


class ConnectorNotFoundError(BSageError):
    """Raised when accessing a connector that is not connected."""


class ConnectorAuthError(BSageError):
    """Raised when connector authentication fails."""


class VaultPathError(BSageError):
    """Raised when a path traversal attempt is detected."""


class SafeModeError(BSageError):
    """Raised when the safe mode system encounters a failure."""
