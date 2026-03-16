"""OntologyRegistry — manages the knowledge graph schema."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger(__name__)

_DEFAULT_ONTOLOGY: dict[str, Any] = {
    "version": "1.0",
    "entity_types": {
        "note": {"description": "A vault note"},
        "person": {"description": "A person"},
        "concept": {"description": "An abstract concept or topic"},
        "project": {"description": "A project or initiative"},
        "event": {"description": "A calendar event or occurrence"},
        "task": {"description": "An actionable task or to-do item"},
        "organization": {"description": "A company, team, or group"},
        "tool": {"description": "A software tool or technology"},
        "tag": {"description": "A categorization tag"},
        "source": {"description": "An input data source"},
    },
    "relationship_types": {
        "related_to": {"description": "General relation between entities"},
        "references": {"description": "One note references another"},
        "tagged_with": {"description": "Entity has a tag"},
        "created_by": {"description": "Entity created by a source"},
        "part_of": {"description": "Entity belongs to another"},
        "uses": {"description": "Entity uses a tool or concept"},
        "depends_on": {"description": "Entity depends on another (task/project dependency)"},
        "assigned_to": {"description": "Task assigned to a person"},
        "attends": {"description": "Person attends an event"},
        "belongs_to": {"description": "Person or entity belongs to an organization"},
        "mentions": {"description": "Entity mentions another in passing"},
    },
}


class OntologyRegistry:
    """Manages the ontology schema for the knowledge graph.

    The schema is stored as YAML at ``vault/.bsage/ontology.yaml``.
    If the file does not exist, a default ontology is created automatically.
    """

    def __init__(self, ontology_path: Path) -> None:
        self._path = ontology_path
        self._data: dict[str, Any] = {}

    async def load(self) -> None:
        """Load the ontology from disk, or create defaults if missing."""

        def _read() -> dict[str, Any] | None:
            if self._path.exists():
                with open(self._path) as f:
                    return yaml.safe_load(f)
            return None

        loaded = await asyncio.to_thread(_read)
        if loaded is not None:
            self._data = loaded if isinstance(loaded, dict) else copy.deepcopy(_DEFAULT_ONTOLOGY)
            logger.info("ontology_loaded", path=str(self._path))
        else:
            self._data = copy.deepcopy(_DEFAULT_ONTOLOGY)
            await self.save()
            logger.info("ontology_created_default", path=str(self._path))

    async def save(self) -> None:
        """Persist the ontology to disk."""
        data = copy.deepcopy(self._data)

        def _write() -> None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        await asyncio.to_thread(_write)

    # ------------------------------------------------------------------
    # Entity types
    # ------------------------------------------------------------------

    def get_entity_types(self) -> dict[str, dict[str, str]]:
        """Return all entity types and their descriptions."""
        return dict(self._data.get("entity_types", {}))

    def is_valid_entity_type(self, entity_type: str) -> bool:
        """Check if an entity type exists in the ontology."""
        return entity_type in self._data.get("entity_types", {})

    async def add_entity_type(self, name: str, description: str) -> bool:
        """Add a new entity type. Returns True if added, False if already exists."""
        types = self._data.setdefault("entity_types", {})
        if name in types:
            return False
        types[name] = {"description": description}
        await self.save()
        logger.info("ontology_entity_type_added", name=name)
        return True

    # ------------------------------------------------------------------
    # Relationship types
    # ------------------------------------------------------------------

    def get_relationship_types(self) -> dict[str, dict[str, str]]:
        """Return all relationship types and their descriptions."""
        return dict(self._data.get("relationship_types", {}))

    def is_valid_relationship_type(self, rel_type: str) -> bool:
        """Check if a relationship type exists in the ontology."""
        return rel_type in self._data.get("relationship_types", {})

    async def add_relationship_type(self, name: str, description: str) -> bool:
        """Add a new relationship type. Returns True if added, False if already exists."""
        types = self._data.setdefault("relationship_types", {})
        if name in types:
            return False
        types[name] = {"description": description}
        await self.save()
        logger.info("ontology_relationship_type_added", name=name)
        return True

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def validate_entity_type(self, entity_type: str) -> str:
        """Return the entity type if valid, otherwise fall back to 'concept'."""
        if self.is_valid_entity_type(entity_type):
            return entity_type
        return "concept"

    def validate_relationship_type(self, rel_type: str) -> str:
        """Return the relationship type if valid, otherwise fall back to 'related_to'."""
        if self.is_valid_relationship_type(rel_type):
            return rel_type
        return "related_to"

    @property
    def version(self) -> str:
        """The ontology schema version."""
        return self._data.get("version", "1.0")
