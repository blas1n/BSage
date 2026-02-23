"""PromptRegistry — loads prompt templates from YAML files."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger(__name__)


class PromptRegistry:
    """Loads and renders prompt templates from a prompts/ directory.

    Each YAML file contains a single ``template`` key with a string value.
    Templates may include ``{variable}`` placeholders for rendering.

    Usage::

        registry = PromptRegistry(Path("prompts"))
        system = registry.get("system")                     # raw template
        chat = registry.render("chat", context_section=ctx) # rendered
    """

    def __init__(self, prompts_dir: Path) -> None:
        self._dir = prompts_dir
        self._templates: dict[str, str] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Scan prompts_dir for *.yaml files and load their templates."""
        if not self._dir.is_dir():
            logger.warning("prompts_dir_missing", path=str(self._dir))
            return

        for path in sorted(self._dir.glob("*.yaml")):
            name = path.stem
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("prompt_load_failed", path=str(path))
                continue

            if not isinstance(data, dict) or "template" not in data:
                logger.warning("prompt_no_template", path=str(path))
                continue

            self._templates[name] = data["template"].rstrip("\n")
            logger.debug("prompt_loaded", name=name)

        logger.info("prompts_loaded", count=len(self._templates))

    def get(self, name: str) -> str:
        """Return the raw template string for *name*.

        Raises:
            KeyError: If no template with that name exists.
        """
        try:
            return self._templates[name]
        except KeyError:
            raise KeyError(f"Prompt template '{name}' not found") from None

    def render(self, name: str, **kwargs: str) -> str:
        """Return the template for *name* with ``{placeholders}`` filled.

        Raises:
            KeyError: If the template name is not found or a placeholder
                      is missing from *kwargs*.
        """
        return self.get(name).format(**kwargs)

    def list_names(self) -> list[str]:
        """Return sorted list of loaded template names."""
        return sorted(self._templates)
