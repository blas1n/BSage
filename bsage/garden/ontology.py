"""OntologyRegistry — manages the knowledge graph schema (v2.2)."""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# v2.2 Default Ontology
# ---------------------------------------------------------------------------

_DEFAULT_ONTOLOGY: dict[str, Any] = {
    "schema_version": 3,
    "updated_at": "",
    "entity_types": {
        "idea": {
            "folder": "ideas/",
            "description": "아이디어, 생각",
            "knowledge_layer": "semantic",
        },
        "insight": {
            "folder": "insights/",
            "description": "분석, 연결된 지식",
            "knowledge_layer": "semantic",
        },
        "person": {
            "folder": "people/",
            "description": "사람",
            "required_fields": ["confidence"],
            "knowledge_layer": "semantic",
        },
        "project": {
            "folder": "projects/",
            "description": "프로젝트",
            "knowledge_layer": "semantic",
        },
        "event": {
            "folder": "events/",
            "description": "일정, 회의, 이벤트",
            "required_fields": ["confidence"],
            "knowledge_layer": "episodic",
        },
        "task": {
            "folder": "tasks/",
            "description": "할 일, 액션 아이템",
            "knowledge_layer": "episodic",
        },
        "fact": {
            "folder": "facts/",
            "description": "시간 바인딩된 명제",
            "required_fields": [
                "subject",
                "predicate",
                "object",
                "valid_from",
                "valid_to",
                "source_type",
                "confidence",
            ],
            "knowledge_layer": "semantic",
        },
        "preference": {
            "folder": "preferences/",
            "description": "선호/성향",
            "required_fields": ["subject", "domain", "source_type", "confidence"],
            "knowledge_layer": "procedural",
        },
        "organization": {
            "folder": "organizations/",
            "description": "회사, 팀, 그룹",
            "knowledge_layer": "semantic",
        },
        "tool": {
            "folder": "tools/",
            "description": "소프트웨어 도구, 기술",
            "knowledge_layer": "semantic",
        },
        "concept": {
            "folder": "concepts/",
            "description": "추상 개념, 토픽",
            "knowledge_layer": "semantic",
        },
        "tag": {
            "description": "분류 태그",
            "knowledge_layer": "semantic",
        },
        "source": {
            "description": "입력 데이터 소스",
            "knowledge_layer": "semantic",
        },
    },
    "relation_types": {
        "related_to": {
            "domain": "*",
            "range": "*",
            "inverse": "related_to",
            "default_weight": 0.5,
            "description": "타입 미분류 임시 관계",
        },
        "references": {
            "domain": "*",
            "range": "*",
            "inverse": "referenced_by",
            "default_weight": 0.3,
            "description": "본문 wikilink 참조",
        },
        "tagged_with": {
            "domain": "*",
            "range": "tag",
            "inverse": "tag_of",
            "default_weight": 0.5,
            "description": "태그 분류",
        },
        "created_by": {
            "domain": "*",
            "range": "source",
            "inverse": "created",
            "default_weight": 0.3,
            "description": "소스에 의해 생성됨",
        },
        "part_of": {
            "domain": "*",
            "range": ["project", "organization"],
            "inverse": "has_member",
            "default_weight": 0.8,
            "description": "소속 관계",
        },
        "uses": {
            "domain": "person",
            "range": ["tool", "concept"],
            "inverse": "used_by",
            "default_weight": 0.9,
            "description": "도구/기술 사용",
        },
        "depends_on": {
            "domain": ["task", "project"],
            "range": ["task", "project"],
            "inverse": "depended_by",
            "default_weight": 0.8,
            "description": "의존 관계",
        },
        "assigned_to": {
            "domain": "task",
            "range": "person",
            "inverse": "assigned_tasks",
            "default_weight": 1.0,
            "description": "담당자 배정",
        },
        "attends": {
            "domain": "person",
            "range": "event",
            "inverse": "attended_by",
            "default_weight": 1.0,
            "description": "이벤트 참석",
        },
        "attendees": {
            "domain": "event",
            "range": "person",
            "inverse": "attends",
            "default_weight": 1.0,
            "description": "이벤트 참석자 (frontmatter key)",
        },
        "belongs_to": {
            "domain": "*",
            "range": ["project", "organization"],
            "inverse": "has_member",
            "default_weight": 0.8,
            "description": "소속",
        },
        "works_on": {
            "domain": "person",
            "range": "project",
            "inverse": "worked_on_by",
            "default_weight": 1.0,
            "description": "프로젝트 참여",
        },
        "mentions": {
            "domain": "*",
            "range": "*",
            "inverse": "mentioned_by",
            "default_weight": 0.1,
            "description": "맥락적 언급",
        },
        "supersedes": {
            "domain": "fact",
            "range": "fact",
            "inverse": "superseded_by",
            "default_weight": 1.0,
            "description": "이전 사실 대체",
        },
        "prefers": {
            "domain": "person",
            "range": "*",
            "inverse": "preferred_by",
            "default_weight": 0.7,
            "description": "선호 관계",
        },
    },
    "evolution_config": {
        "create_threshold": 5,
        "merge_jaccard_threshold": 0.7,
        "deprecate_days": 90,
        "deprecate_min_confidence": 0.3,
        "promotion_frequency_ratio": 2.0,
        "edge_promotion_min_mentions": 3,
        "edge_decay_days": 90,
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

    def get_entity_types(self) -> dict[str, dict[str, Any]]:
        """Return all non-deprecated entity types."""
        return {
            k: v for k, v in self._data.get("entity_types", {}).items() if not v.get("deprecated")
        }

    def get_all_entity_types(self) -> dict[str, dict[str, Any]]:
        """Return all entity types including deprecated ones."""
        return dict(self._data.get("entity_types", {}))

    def is_valid_entity_type(self, entity_type: str) -> bool:
        """Check if an entity type exists and is not deprecated."""
        types = self._data.get("entity_types", {})
        entry = types.get(entity_type)
        return entry is not None and not entry.get("deprecated", False)

    async def add_entity_type(
        self,
        name: str,
        description: str,
        *,
        folder: str | None = None,
        knowledge_layer: str = "semantic",
        required_fields: list[str] | None = None,
    ) -> bool:
        """Add a new entity type. Returns True if added, False if already exists."""
        types = self._data.setdefault("entity_types", {})
        if name in types:
            return False
        entry: dict[str, Any] = {
            "description": description,
            "knowledge_layer": knowledge_layer,
        }
        if folder:
            entry["folder"] = folder
        if required_fields:
            entry["required_fields"] = required_fields
        types[name] = entry
        await self.save()
        logger.info("ontology_entity_type_added", name=name)
        return True

    def get_entity_folder(self, entity_type: str) -> str | None:
        """Return the vault folder for an entity type, or None."""
        types = self._data.get("entity_types", {})
        entry = types.get(entity_type)
        if entry:
            return entry.get("folder")
        return None

    def get_knowledge_layer(self, entity_type: str) -> str:
        """Return the default knowledge layer for an entity type."""
        types = self._data.get("entity_types", {})
        entry = types.get(entity_type, {})
        return entry.get("knowledge_layer", "semantic")

    # ------------------------------------------------------------------
    # Relationship types
    # ------------------------------------------------------------------

    def get_relation_types(self) -> dict[str, dict[str, Any]]:
        """Return all relation types."""
        return dict(self._data.get("relation_types", {}))

    # Keep old name as alias for compatibility during transition
    get_relationship_types = get_relation_types

    def is_valid_relationship_type(self, rel_type: str) -> bool:
        """Check if a relationship type exists in the ontology."""
        return rel_type in self._data.get("relation_types", {})

    async def add_relationship_type(
        self,
        name: str,
        description: str,
        *,
        domain: str | list[str] = "*",
        range_: str | list[str] = "*",
        inverse: str | None = None,
        default_weight: float = 0.5,
    ) -> bool:
        """Add a new relationship type. Returns True if added, False if already exists."""
        types = self._data.setdefault("relation_types", {})
        if name in types:
            return False
        entry: dict[str, Any] = {
            "domain": domain,
            "range": range_,
            "default_weight": default_weight,
            "description": description,
        }
        if inverse:
            entry["inverse"] = inverse
        types[name] = entry
        await self.save()
        logger.info("ontology_relationship_type_added", name=name)
        return True

    def get_relation_weight(self, rel_type: str) -> float:
        """Return the default weight for a relation type."""
        types = self._data.get("relation_types", {})
        entry = types.get(rel_type, {})
        return float(entry.get("default_weight", 0.5))

    def get_inverse(self, rel_type: str) -> str | None:
        """Return the inverse relation type, or None."""
        types = self._data.get("relation_types", {})
        entry = types.get(rel_type)
        if entry:
            return entry.get("inverse")
        return None

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

    # ------------------------------------------------------------------
    # Evolution config
    # ------------------------------------------------------------------

    def get_evolution_config(self) -> dict[str, Any]:
        """Return the evolution configuration."""
        return dict(self._data.get("evolution_config", {}))

    # ------------------------------------------------------------------
    # Schema evolution operations (v2.2)
    # ------------------------------------------------------------------

    async def deprecate_entity_type(self, name: str, *, reason: str = "") -> bool:
        """Mark an entity type as deprecated. Returns True if changed."""
        types = self._data.get("entity_types", {})
        entry = types.get(name)
        if entry is None or entry.get("deprecated"):
            return False
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        entry["deprecated"] = True
        entry["deprecated_at"] = today
        await self.save()
        await self._append_changelog("DEPRECATE", f"Entity type `{name}` deprecated. {reason}")
        logger.info("ontology_entity_type_deprecated", name=name, reason=reason)
        return True

    async def merge_entity_types(
        self, source_name: str, target_name: str, *, reason: str = ""
    ) -> bool:
        """Merge *source_name* into *target_name* (deprecate source).

        Returns True if the merge was performed.
        """
        types = self._data.get("entity_types", {})
        source = types.get(source_name)
        target = types.get(target_name)
        if source is None or target is None:
            return False
        if source.get("deprecated"):
            return False
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        source["deprecated"] = True
        source["deprecated_at"] = today
        source["merged_into"] = target_name
        # Preserve old name as alias description
        await self.save()
        await self._append_changelog(
            "MERGE",
            f"`{source_name}` merged into `{target_name}`. {reason}",
        )
        logger.info(
            "ontology_entity_types_merged",
            source=source_name,
            target=target_name,
            reason=reason,
        )
        return True

    async def split_entity_type(
        self,
        original: str,
        new_name: str,
        new_description: str,
        *,
        reason: str = "",
        knowledge_layer: str = "semantic",
        folder: str | None = None,
    ) -> bool:
        """Split a subset of *original* into a new type *new_name*.

        Returns True if the new type was created.
        """
        types = self._data.get("entity_types", {})
        if original not in types or new_name in types:
            return False
        entry: dict[str, Any] = {
            "description": new_description,
            "knowledge_layer": knowledge_layer,
            "split_from": original,
        }
        if folder:
            entry["folder"] = folder
        types[new_name] = entry
        await self.save()
        await self._append_changelog(
            "SPLIT",
            f"`{original}` split → new type `{new_name}`. {reason}",
        )
        logger.info("ontology_entity_type_split", original=original, new_name=new_name)
        return True

    async def promote_entity_type(self, name: str, *, reason: str = "") -> bool:
        """Promote an entity type to top-level (placeholder for hierarchy changes).

        Currently logs the promotion; hierarchy data model is a future extension.
        Returns True if the type exists and was logged.
        """
        types = self._data.get("entity_types", {})
        if name not in types:
            return False
        await self._append_changelog("PROMOTE", f"Entity type `{name}` promoted. {reason}")
        logger.info("ontology_entity_type_promoted", name=name, reason=reason)
        return True

    # ------------------------------------------------------------------
    # Changelog
    # ------------------------------------------------------------------

    async def _append_changelog(self, operation: str, detail: str) -> None:
        """Append an entry to ontology-changelog.md next to ontology.yaml."""
        changelog_path = self._path.parent / "ontology-changelog.md"
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        version = self.schema_version
        entry = f"\n## {today} — schema v{version}\n\n### {operation}\n- {detail}\n"

        def _write() -> None:
            if changelog_path.exists():
                with open(changelog_path, "a", encoding="utf-8") as f:
                    f.write(entry)
            else:
                changelog_path.write_text(f"# Ontology Changelog\n{entry}", encoding="utf-8")

        await asyncio.to_thread(_write)

    # ------------------------------------------------------------------
    # Schema metadata
    # ------------------------------------------------------------------

    @property
    def schema_version(self) -> int:
        """The ontology schema version."""
        return int(self._data.get("schema_version", 1))

    # Keep old property for transition
    @property
    def version(self) -> str:
        return str(self.schema_version)
