"""Data models for the BSage knowledge graph."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class GraphEntity:
    """A node in the knowledge graph.

    Attributes:
        id: Unique identifier.
        name: Human-readable entity name.
        entity_type: Ontology type (person, concept, project, tool, tag, source, note).
        source_path: Vault-relative path of the note that produced this entity.
        properties: Arbitrary key-value metadata.
        confidence: Extraction confidence (1.0 for rule-based, <1.0 for LLM).
    """

    name: str
    entity_type: str
    source_path: str
    id: str = field(default_factory=_new_id)
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class GraphRelationship:
    """An edge in the knowledge graph.

    Attributes:
        id: Unique identifier.
        source_id: Entity ID of the source node.
        target_id: Entity ID of the target node.
        rel_type: Ontology relationship type (related_to, references, tagged_with, etc.).
        source_path: Vault-relative path of the note that produced this relationship.
        properties: Arbitrary key-value metadata.
        confidence: Extraction confidence.
    """

    source_id: str
    target_id: str
    rel_type: str
    source_path: str
    id: str = field(default_factory=_new_id)
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class ProvenanceRecord:
    """Tracks how an entity was extracted.

    Attributes:
        entity_id: The entity this record belongs to.
        source_path: Vault-relative path of the originating note.
        extraction_method: "rule" or "llm".
        confidence: Extraction confidence score.
        extracted_at: ISO-format UTC timestamp.
    """

    entity_id: str
    source_path: str
    extraction_method: str
    confidence: float
    extracted_at: str
