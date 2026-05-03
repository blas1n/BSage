"""PluginLoader — scans plugins/ directory, loads @plugin-decorated modules."""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from bsage.core.exceptions import PluginLoadError

logger = structlog.get_logger(__name__)

_VALID_CATEGORIES = {"input", "process", "output"}
_REQUIRED_META_FIELDS = {"name", "category"}


@dataclass
class PluginMeta:
    """Metadata and runtime references for a loaded Plugin."""

    name: str
    version: str
    category: str  # input | process | output
    description: str
    author: str = ""
    trigger: dict[str, Any] | None = None
    credentials: list[dict[str, Any]] | None = None
    input_schema: dict[str, Any] | None = None
    mcp_exposed: bool = False  # True → register as MCP tool for external clients

    # Runtime function references — set by PluginLoader, not serialised
    _execute_fn: Callable | None = field(default=None, repr=False, compare=False)
    _notify_fn: Callable | None = field(default=None, repr=False, compare=False)
    _setup_fn: Callable | None = field(default=None, repr=False, compare=False)


class PluginLoader:
    """Scans a plugins directory for plugin.py files decorated with @plugin."""

    def __init__(
        self,
        plugins_dir: Path,
        danger_analyzer: Any | None = None,
    ) -> None:
        self._plugins_dir = plugins_dir
        self._danger_analyzer = danger_analyzer
        self._registry: dict[str, PluginMeta] = {}
        self.danger_map: dict[str, bool] = {}

    async def load_all(self) -> dict[str, PluginMeta]:
        """Scan plugins_dir and load all valid Plugin metadata into the registry."""
        self._registry.clear()
        self.danger_map.clear()

        if not self._plugins_dir.is_dir():
            logger.warning("plugins_dir_missing", path=str(self._plugins_dir))
            return self._registry

        for entry in sorted(self._plugins_dir.iterdir()):
            if not entry.is_dir():
                continue

            plugin_py = entry / "plugin.py"
            if not plugin_py.exists():
                logger.warning("plugin_missing_file", path=str(entry))
                continue

            # Check requirements.txt before loading the plugin module
            missing_deps = self._check_requirements(entry)
            if missing_deps:
                logger.warning(
                    "plugin_skipped_missing_deps",
                    name=entry.name,
                    missing=missing_deps,
                    hint=f"Install with: bsage install {entry.name}",
                )
                continue

            try:
                meta = self._load_plugin(plugin_py)
                if self._danger_analyzer is not None:
                    code = plugin_py.read_text(encoding="utf-8")
                    is_dangerous, reason = await self._danger_analyzer.analyze(
                        meta.name, code, meta.description
                    )
                    self.danger_map[meta.name] = is_dangerous
                    logger.info(
                        "plugin_danger_assessed",
                        name=meta.name,
                        is_dangerous=is_dangerous,
                        reason=reason,
                    )
                else:
                    self.danger_map[meta.name] = False
                self._registry[meta.name] = meta
                logger.info("plugin_loaded", name=meta.name, category=meta.category)
            except Exception as exc:
                logger.warning("plugin_load_failed", path=str(plugin_py), error=str(exc))

        return self._registry

    async def scan_new(self) -> dict[str, PluginMeta]:
        """Scan for plugins not yet in the registry. Only loads new entries.

        Unlike ``load_all()``, this method does NOT clear the registry.
        It only discovers and loads plugins whose directory name is not
        already present, making it safe and cheap to call on every request.

        Returns:
            Dict of newly loaded plugin name → PluginMeta (empty if nothing new).
        """
        new_entries: dict[str, PluginMeta] = {}
        if not self._plugins_dir.is_dir():
            return new_entries

        for entry in sorted(self._plugins_dir.iterdir()):
            if not entry.is_dir():
                continue

            plugin_py = entry / "plugin.py"
            if not plugin_py.exists():
                continue

            # Skip directories whose name is already registered
            if entry.name in self._registry:
                continue

            # Check requirements.txt before loading the plugin module
            missing_deps = self._check_requirements(entry)
            if missing_deps:
                logger.warning(
                    "plugin_skipped_missing_deps",
                    name=entry.name,
                    missing=missing_deps,
                    hint=f"Install with: bsage install {entry.name}",
                )
                continue

            try:
                meta = self._load_plugin(plugin_py)
                if meta.name in self._registry:
                    continue  # name registered under a different directory

                if self._danger_analyzer is not None:
                    code = plugin_py.read_text(encoding="utf-8")
                    is_dangerous, reason = await self._danger_analyzer.analyze(
                        meta.name, code, meta.description
                    )
                    self.danger_map[meta.name] = is_dangerous
                    logger.info(
                        "plugin_danger_assessed",
                        name=meta.name,
                        is_dangerous=is_dangerous,
                        reason=reason,
                    )
                else:
                    self.danger_map[meta.name] = False

                self._registry[meta.name] = meta
                new_entries[meta.name] = meta
                logger.info("plugin_hot_loaded", name=meta.name, category=meta.category)
            except Exception as exc:
                logger.warning("plugin_hot_load_failed", path=str(plugin_py), error=str(exc))

        return new_entries

    def get(self, name: str) -> PluginMeta:
        """Retrieve a loaded PluginMeta by name."""
        if name not in self._registry:
            raise PluginLoadError(f"Plugin '{name}' not found in registry")
        return self._registry[name]

    @staticmethod
    def _check_requirements(plugin_dir: Path) -> list[str]:
        """Return list of missing packages declared in the plugin's requirements.txt.

        If the file does not exist the plugin has no external dependencies
        and an empty list is returned.
        """
        req_file = plugin_dir / "requirements.txt"
        if not req_file.exists():
            return []
        missing: list[str] = []
        for raw_line in req_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip version specifiers: httpx>=0.27.0 → httpx
            for sep in (">=", "==", ">", "<", "!=", "~="):
                line = line.split(sep)[0]
            pkg = line.strip()
            if not pkg:
                continue
            # Normalize pip package name to Python import name
            import_name = pkg.lower().replace("-", "_")
            if importlib.util.find_spec(import_name) is None:
                missing.append(pkg)
        return missing

    @staticmethod
    def _load_plugin(path: Path) -> PluginMeta:
        """Import plugin.py, find the @plugin-decorated function, return PluginMeta."""
        spec = importlib.util.spec_from_file_location("_bsage_plugin", path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Cannot load plugin module: {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find the execute function decorated with @plugin (has __plugin__ attribute)
        execute_fn: Callable | None = None
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if callable(obj) and hasattr(obj, "__plugin__"):
                execute_fn = obj
                break

        if execute_fn is None:
            raise PluginLoadError(f"No @plugin-decorated function found in {path}")

        meta_dict: dict[str, Any] = execute_fn.__plugin__

        # Validate required fields
        missing = _REQUIRED_META_FIELDS - set(meta_dict.keys())
        if missing:
            raise PluginLoadError(f"Missing required plugin fields in {path}: {missing}")

        name = meta_dict.get("name", "")
        if not re.match(r"^[a-z][a-z0-9-]*$", name):
            raise PluginLoadError(
                f"Invalid plugin name '{name}' in {path}. Use lowercase alphanumeric with hyphens."
            )

        category = meta_dict.get("category", "")
        if category not in _VALID_CATEGORIES:
            valid = ", ".join(sorted(_VALID_CATEGORIES))
            raise PluginLoadError(f"Invalid category '{category}' in {path}. Must be: {valid}")

        notify_fn: Callable | None = getattr(execute_fn, "__notify__", None)
        setup_fn: Callable | None = getattr(execute_fn, "__setup__", None)

        meta = PluginMeta(
            name=name,
            version=meta_dict.get("version", ""),
            category=category,
            description=meta_dict.get("description", ""),
            author=meta_dict.get("author", ""),
            trigger=meta_dict.get("trigger"),
            credentials=meta_dict.get("credentials"),
            input_schema=meta_dict.get("input_schema"),
            mcp_exposed=bool(meta_dict.get("mcp_exposed", False)),
            _execute_fn=execute_fn,
            _notify_fn=notify_fn,
            _setup_fn=setup_fn,
        )
        return meta
