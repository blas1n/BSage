"""RuntimeConfig — mutable runtime settings with JSON persistence."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from bsage.core.config import Settings

logger = structlog.get_logger(__name__)

_SENTINEL = object()


class RuntimeConfig:
    """Thread-safe mutable configuration for values that can change at runtime.

    Initialized from Settings at startup, optionally loading overrides from a
    persisted JSON file. Updates are written back to the JSON file so they
    survive server restarts.

    Components (LiteLLMClient, SafeModeGuard) hold a reference to this object
    and read its properties on every call.
    """

    def __init__(
        self,
        llm_model: str,
        llm_api_key: str,
        llm_api_base: str | None,
        safe_mode: bool,
        persist_path: Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._llm_model = llm_model
        self._llm_api_key = llm_api_key
        self._llm_api_base = llm_api_base
        self._safe_mode = safe_mode
        self._persist_path = persist_path

    @property
    def llm_model(self) -> str:
        with self._lock:
            return self._llm_model

    @property
    def llm_api_key(self) -> str:
        with self._lock:
            return self._llm_api_key

    @property
    def llm_api_base(self) -> str | None:
        with self._lock:
            return self._llm_api_base

    @property
    def safe_mode(self) -> bool:
        with self._lock:
            return self._safe_mode

    def update_llm(
        self,
        model: str | None = None,
        api_key: str | None = None,
        api_base: Any = _SENTINEL,
    ) -> None:
        """Update LLM settings. Only provided values are changed.

        Args:
            model: New LLM model identifier. Cannot be empty.
            api_key: New API key.
            api_base: New API base URL. Pass None to clear.
                      Omit (default sentinel) to leave unchanged.

        Raises:
            ValueError: If model is empty or whitespace.
        """
        with self._lock:
            if model is not None:
                if not model.strip():
                    raise ValueError("LLM model cannot be empty")
                self._llm_model = model
            if api_key is not None:
                self._llm_api_key = api_key
            if api_base is not _SENTINEL:
                self._llm_api_base = api_base
            logger.info("runtime_config_llm_updated", model=self._llm_model)
            self._persist_locked()

    def update_safe_mode(self, enabled: bool) -> None:
        """Enable or disable safe mode at runtime."""
        with self._lock:
            self._safe_mode = enabled
            logger.info("runtime_config_safe_mode_updated", enabled=enabled)
            self._persist_locked()

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable snapshot of current config (api_key excluded)."""
        with self._lock:
            return {
                "llm_model": self._llm_model,
                "llm_api_base": self._llm_api_base,
                "safe_mode": self._safe_mode,
            }

    def _persist_locked(self) -> None:
        """Write current state to JSON file. Must be called with lock held.

        Persistence failures are logged but never propagated — in-memory
        state has already been updated and should remain consistent.
        """
        if self._persist_path is None:
            return
        data = {
            "llm_model": self._llm_model,
            "llm_api_key": self._llm_api_key,
            "llm_api_base": self._llm_api_base,
            "safe_mode": self._safe_mode,
        }
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

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        persist_path: Path | None,
    ) -> RuntimeConfig:
        """Create a RuntimeConfig from Settings, loading JSON overrides if present.

        Priority: JSON file overrides > Settings defaults.
        If the JSON file is missing or invalid, Settings values are used.

        Args:
            settings: A Settings instance with llm_model, llm_api_key,
                      llm_api_base, safe_mode attributes.
            persist_path: Path to the JSON persistence file, or None to skip.

        Returns:
            A new RuntimeConfig instance.
        """
        llm_model = settings.llm_model
        llm_api_key = settings.llm_api_key
        llm_api_base = settings.llm_api_base
        safe_mode = settings.safe_mode

        if persist_path and persist_path.exists():
            try:
                data = json.loads(persist_path.read_text(encoding="utf-8"))
                llm_model = data.get("llm_model", llm_model)
                llm_api_key = data.get("llm_api_key", llm_api_key)
                llm_api_base = data.get("llm_api_base", llm_api_base)
                safe_mode = data.get("safe_mode", safe_mode)
                logger.info(
                    "runtime_config_loaded_from_file",
                    path=str(persist_path),
                )
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "runtime_config_file_invalid",
                    path=str(persist_path),
                )

        return cls(
            llm_model=llm_model,
            llm_api_key=llm_api_key,
            llm_api_base=llm_api_base,
            safe_mode=safe_mode,
            persist_path=persist_path,
        )
