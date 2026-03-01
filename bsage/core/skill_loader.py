"""SkillLoader — scans skills/ directory for *.md files, builds registry."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import structlog
import yaml

from bsage.core.exceptions import SkillLoadError

logger = structlog.get_logger(__name__)

_REQUIRED_FIELDS = {"name", "version", "category", "description"}
_VALID_CATEGORIES = {"input", "process", "output"}


class OutputTarget(Enum):
    """Valid output targets for Skill LLM pipeline."""

    GARDEN = "garden"
    SEEDS = "seeds"


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split a Markdown document with YAML frontmatter into (frontmatter, body).

    Expects the format::

        ---
        key: value
        ---

        Body content here.

    Returns:
        Tuple of (frontmatter_yaml_string, body_string).
        If no frontmatter delimiters are found, returns ("", text).
    """
    if not text.startswith("---\n"):
        return "", text
    try:
        end_idx = text.index("\n---\n", 4)
    except ValueError:
        return "", text
    frontmatter = text[4:end_idx]
    body = text[end_idx + 5 :]  # skip past \n---\n
    return frontmatter, body


@dataclass
class SkillMeta:
    """Metadata for a Skill parsed from a skill.md file.

    The frontmatter provides pipeline configuration and the Markdown body
    serves as the LLM system prompt.
    """

    name: str
    version: str
    category: str  # input | process | output
    description: str
    author: str = ""
    trigger: dict | None = None
    credentials: dict | None = None

    # LLM pipeline fields (YAML-only / Skill-specific)
    read_context: list[str] = field(default_factory=list)
    output_target: OutputTarget | None = None
    output_note_type: str = "idea"
    output_format: str | None = None

    # LLM system prompt — loaded from the Markdown body
    system_prompt: str | None = None


class SkillLoader:
    """Scans a skills directory for *.md files and builds a SkillMeta registry."""

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir
        self._registry: dict[str, SkillMeta] = {}

    async def load_all(self) -> dict[str, SkillMeta]:
        """Scan skills_dir for *.md files and load all valid Skill metadata."""
        self._registry.clear()

        if not self._skills_dir.is_dir():
            logger.warning("skills_dir_missing", path=str(self._skills_dir))
            return self._registry

        for md_path in sorted(self._skills_dir.glob("*.md")):
            if not md_path.is_file():
                continue
            try:
                meta = self._parse_md(md_path)
                self._registry[meta.name] = meta
                logger.info("skill_loaded", name=meta.name, category=meta.category)
            except Exception as exc:
                logger.warning("skill_load_failed", path=str(md_path), error=str(exc))

        return self._registry

    async def scan_new(self) -> dict[str, SkillMeta]:
        """Scan for skills not yet in the registry. Only loads new entries.

        Unlike ``load_all()``, this method does NOT clear the registry.
        It only discovers and loads ``.md`` files whose stem is not
        already present, making it safe and cheap to call on every request.

        Returns:
            Dict of newly loaded skill name → SkillMeta (empty if nothing new).
        """
        new_entries: dict[str, SkillMeta] = {}
        if not self._skills_dir.is_dir():
            return new_entries

        for md_path in sorted(self._skills_dir.glob("*.md")):
            if not md_path.is_file():
                continue

            # Skip files whose stem is already registered
            if md_path.stem in self._registry:
                continue

            try:
                meta = self._parse_md(md_path)
                if meta.name in self._registry:
                    continue  # name registered under a different file

                self._registry[meta.name] = meta
                new_entries[meta.name] = meta
                logger.info("skill_hot_loaded", name=meta.name, category=meta.category)
            except Exception as exc:
                logger.warning("skill_hot_load_failed", path=str(md_path), error=str(exc))

        return new_entries

    def get(self, name: str) -> SkillMeta:
        """Retrieve a loaded SkillMeta by name.

        Raises:
            SkillLoadError: If the skill is not found in the registry.
        """
        if name not in self._registry:
            raise SkillLoadError(f"Skill '{name}' not found in registry")
        return self._registry[name]

    @staticmethod
    def _parse_md(path: Path) -> SkillMeta:
        """Parse a skill.md file into a SkillMeta dataclass.

        The file must start with YAML frontmatter (---) followed by the
        Markdown body, which becomes the LLM system prompt.

        Raises:
            SkillLoadError: If required fields are missing or invalid.
            yaml.YAMLError: If the frontmatter YAML is malformed.
        """
        text = path.read_text(encoding="utf-8")
        frontmatter_str, body = _split_frontmatter(text)

        if not frontmatter_str:
            raise SkillLoadError(f"No YAML frontmatter found in {path}")

        data = yaml.safe_load(frontmatter_str)
        if not isinstance(data, dict):
            raise SkillLoadError(f"Invalid frontmatter structure in {path}")

        missing = _REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise SkillLoadError(f"Missing required fields in {path}: {missing}")

        name = data.get("name", "")
        if not re.match(r"^[a-z][a-z0-9-]*$", name):
            raise SkillLoadError(
                f"Invalid skill name '{name}' in {path}. Use lowercase alphanumeric with hyphens."
            )

        category = data.get("category", "")
        if category not in _VALID_CATEGORIES:
            valid = ", ".join(sorted(_VALID_CATEGORIES))
            hint = (
                " ('meta' is removed — use 'input', 'process', or 'output')"
                if category == "meta"
                else ""
            )
            raise SkillLoadError(f"Invalid category '{category}' in {path}.{hint} Must be: {valid}")

        # Validate and convert output_target to enum
        raw_target = data.get("output_target")
        if raw_target is not None:
            try:
                data["output_target"] = OutputTarget(raw_target)
            except ValueError:
                valid = ", ".join(t.value for t in OutputTarget)
                raise SkillLoadError(
                    f"Invalid output_target '{raw_target}' in {path}. Must be: {valid}"
                ) from None

        known_fields = {f for f in SkillMeta.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known_fields}

        # is_dangerous is always False for YAML-only skills (structural guarantee).
        # Ignore any author-declared value.
        filtered.pop("is_dangerous", None)

        # Markdown body becomes the system prompt (overrides inline system_prompt if both present)
        body_stripped = body.strip()
        if body_stripped:
            filtered["system_prompt"] = body_stripped

        return SkillMeta(**filtered)
