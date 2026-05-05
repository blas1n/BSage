"""RuntimeConfig — mutable runtime settings with JSON persistence.

Adding a new runtime-configurable field:
  1. Add it to _ConfigState below.
  2. Add a matching attribute to Settings in config.py.
  3. If it's a secret, add its name to _SECRET_FIELDS.
No other changes needed — update(), snapshot(), persist, and
from_settings() adapt automatically.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from bsage.core.config import Settings
    from bsage.core.credential_store import CredentialStore

logger = structlog.get_logger(__name__)


@dataclass
class _ConfigState:
    """All mutable config fields live here."""

    llm_model: str
    llm_api_key: str
    llm_api_base: str | None
    safe_mode: bool
    bsgateway_url: str = ""
    disabled_entries: list[str] = field(default_factory=list)


# Pre-computed at import time — avoids repeated introspection.
_STATE_FIELD_NAMES: frozenset[str] = frozenset(f.name for f in dc_fields(_ConfigState))
_SECRET_FIELDS: frozenset[str] = frozenset({"llm_api_key"})


def _validate(kwargs: dict[str, Any]) -> None:
    """Run field-level validation on provided kwargs.

    To add validation for a new field, add an ``if`` block here.
    """
    if "llm_model" in kwargs:
        model = kwargs["llm_model"]
        if isinstance(model, str) and not model.strip():
            raise ValueError("LLM model cannot be empty")


class RuntimeConfig:
    """Thread-safe mutable configuration for values that can change at runtime.

    Holds a ``_ConfigState`` dataclass behind a threading lock.
    Components (LiteLLMClient, SafeModeGuard) keep a reference and read
    properties on every call, so runtime changes take effect immediately.
    """

    def __init__(self, *, persist_path: Path | None = None, **fields: Any) -> None:
        self._lock = threading.Lock()
        self._state = _ConfigState(**fields)
        self._persist_path = persist_path
        self._enabled_entries: set[str] = set()

    # -- thread-safe attribute access ----------------------------------------

    def __getattr__(self, name: str) -> Any:
        """Provide thread-safe reads for every ``_ConfigState`` field."""
        if name in _STATE_FIELD_NAMES:
            with self._lock:
                return getattr(self._state, name)
        raise AttributeError(f"RuntimeConfig has no attribute '{name}'")

    @property
    def enabled_entries(self) -> set[str]:
        """Return the current set of enabled entry names (thread-safe)."""
        with self._lock:
            return set(self._enabled_entries)

    def rebuild_enabled(
        self,
        registry: dict[str, Any],
        credential_store: CredentialStore,
    ) -> None:
        """Recompute enabled entries from registry, disabled list, and credentials.

        An entry is enabled when it is NOT in ``disabled_entries`` and, if it
        declares required credentials, those credentials have been configured.
        """
        configured = set(credential_store.list_services())
        with self._lock:
            disabled = set(self._state.disabled_entries)
        enabled: set[str] = set()
        for name, meta in registry.items():
            if name in disabled:
                continue
            creds = getattr(meta, "credentials", None)
            if isinstance(creds, list) and creds:
                required = [f["name"] for f in creds if f.get("required", True)]
                if required and name not in configured:
                    continue
            enabled.add(name)
        with self._lock:
            self._enabled_entries = enabled
        logger.info("enabled_entries_rebuilt", count=len(enabled))

    # -- mutations -----------------------------------------------------------

    def update(self, **kwargs: Any) -> None:
        """Update one or more config fields atomically.

        Only provided keyword arguments are changed.

        Raises:
            ValueError: If a field name is unknown or validation fails.
        """
        unknown = set(kwargs) - _STATE_FIELD_NAMES
        if unknown:
            raise ValueError(f"Unknown config fields: {unknown}")

        _validate(kwargs)

        with self._lock:
            for key, value in kwargs.items():
                setattr(self._state, key, value)
            logger.info("runtime_config_updated", fields=list(kwargs.keys()))
            self._persist_locked()

    # -- serialization -------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable snapshot of current config (secrets excluded)."""
        with self._lock:
            return {
                f.name: getattr(self._state, f.name)
                for f in dc_fields(self._state)
                if f.name not in _SECRET_FIELDS
            }

    def _persist_locked(self) -> None:
        """Write current state to JSON file. Must be called with lock held.

        Persistence failures are logged but never propagated — in-memory
        state has already been updated and should remain consistent.
        """
        if self._persist_path is None:
            return
        data = {f.name: getattr(self._state, f.name) for f in dc_fields(self._state)}
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )
            logger.debug("runtime_config_persisted", path=str(self._persist_path))
        except OSError:
            logger.warning(
                "runtime_config_persist_failed",
                path=str(self._persist_path),
                exc_info=True,
            )

    # -- factory -------------------------------------------------------------

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        persist_path: Path | None,
    ) -> RuntimeConfig:
        """Create a RuntimeConfig from Settings, loading JSON overrides.

        Priority: JSON file overrides > Settings defaults.
        If the JSON file is missing or invalid, Settings values are used.
        """
        values = {name: getattr(settings, name) for name in _STATE_FIELD_NAMES}

        if persist_path and persist_path.exists():
            try:
                data = json.loads(persist_path.read_text(encoding="utf-8"))
                for name in _STATE_FIELD_NAMES:
                    if name in data:
                        values[name] = data[name]
                logger.info(
                    "runtime_config_loaded_from_file",
                    path=str(persist_path),
                )
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "runtime_config_file_invalid",
                    path=str(persist_path),
                )

        return cls(persist_path=persist_path, **values)
