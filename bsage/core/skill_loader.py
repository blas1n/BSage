"""SkillLoader — scans skills/ directory, parses YAML, builds registry."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml

from bsage.core.exceptions import SkillLoadError

logger = structlog.get_logger(__name__)

_REQUIRED_FIELDS = {"name", "version", "category", "is_dangerous", "description"}


@dataclass
class SkillMeta:
    """Metadata for a single Skill, parsed from skill.yaml."""

    name: str
    version: str
    category: str  # input / process / output / meta
    is_dangerous: bool
    description: str
    author: str = ""
    requires_connector: str | None = None
    entrypoint: str | None = None
    trigger: dict | None = None
    rules: list[str] = field(default_factory=list)


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

        known_fields = {f.name for f in SkillMeta.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return SkillMeta(**filtered)
