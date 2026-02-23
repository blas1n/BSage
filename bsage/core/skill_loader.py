"""SkillLoader — scans skills/ directory, parses YAML, builds registry."""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import structlog
import yaml

from bsage.core.exceptions import SkillLoadError

logger = structlog.get_logger(__name__)

_REQUIRED_FIELDS = {"name", "version", "category", "is_dangerous", "description"}


_VALID_CATEGORIES = {"input", "process", "output"}


class OutputTarget(Enum):
    """Valid output targets for YAML-only skills."""

    GARDEN = "garden"
    SEEDS = "seeds"


@dataclass
class SkillMeta:
    """Metadata for a single Skill, parsed from skill.yaml."""

    name: str
    version: str
    category: str  # input / process / output
    is_dangerous: bool
    description: str
    author: str = ""
    entrypoint: str | None = None
    trigger: dict | None = None
    credentials: dict | None = None
    notification_entrypoint: str | None = None

    # YAML-only skill fields (used when entrypoint is None)
    read_context: list[str] = field(default_factory=list)
    output_target: OutputTarget | None = None
    output_note_type: str = "idea"
    system_prompt: str | None = None
    output_format: str | None = None


class SkillLoader:
    """Scans a skills directory for skill.yaml files and builds a registry."""

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir
        self._registry: dict[str, SkillMeta] = {}

    async def load_all(self) -> dict[str, SkillMeta]:
        """Scan skills_dir and load all valid Skill metadata into the registry."""
        self._registry.clear()

        if not self._skills_dir.is_dir():
            logger.warning("skills_dir_missing", path=str(self._skills_dir))
            return self._registry

        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir():
                continue

            yaml_path = entry / "skill.yaml"
            if not yaml_path.exists():
                logger.warning("skill_missing_yaml", path=str(entry))
                continue

            try:
                meta = self._parse_yaml(yaml_path)
                self._registry[meta.name] = meta
                logger.info("skill_loaded", name=meta.name, category=meta.category)
            except Exception as exc:
                logger.warning("skill_load_failed", path=str(yaml_path), error=str(exc))

        return self._registry

    def get(self, name: str) -> SkillMeta:
        """Retrieve a loaded SkillMeta by name.

        Raises:
            SkillLoadError: If the skill is not found in the registry.
        """
        if name not in self._registry:
            raise SkillLoadError(f"Skill '{name}' not found in registry")
        return self._registry[name]

    @staticmethod
    def _parse_yaml(path: Path) -> SkillMeta:
        """Parse a skill.yaml file into a SkillMeta dataclass.

        Raises:
            SkillLoadError: If required fields are missing.
            yaml.YAMLError: If the YAML is malformed.
        """
        with open(path) as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise SkillLoadError(f"Invalid YAML structure in {path}")

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

        known_fields = {f.name for f in SkillMeta.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return SkillMeta(**filtered)
