"""GraphExtractor — rule-based entity and relationship extraction from vault notes."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import structlog

from bsage.core.patterns import WIKILINK_RE
from bsage.garden.graph_models import GraphEntity, GraphRelationship
from bsage.garden.markdown_utils import body_after_frontmatter, extract_frontmatter

if TYPE_CHECKING:
    from bsage.garden.llm_extractor import LLMExtractor

logger = structlog.get_logger(__name__)

# Frontmatter type → entity_type mapping
_TYPE_MAP: dict[str, str] = {
    "idea": "note",
    "insight": "note",
    "project": "project",
    "event": "note",
    "seed": "note",
}


def _slug_from_path(path: str) -> str:
    """Derive a human-readable name from a vault-relative path."""
    stem = PurePosixPath(path).stem
    return stem.replace("-", " ").replace("_", " ").strip()


class GraphExtractor:
    """Extracts entities and relationships from vault note content.

    Primary extraction is deterministic rule-based (confidence=1.0).
    When an ``LLMExtractor`` is provided, also extracts from unstructured
    body text using LLM (confidence=0.8).
    """

    def __init__(self, llm_extractor: LLMExtractor | None = None) -> None:
        self._llm_extractor = llm_extractor

    def extract_from_note(
        self, rel_path: str, content: str
    ) -> tuple[list[GraphEntity], list[GraphRelationship]]:
        """Extract entities and relationships from a single note.

        Args:
            rel_path: Vault-relative path (e.g. ``garden/idea/bsage.md``).
            content: Full markdown content of the note.

        Returns:
            Tuple of (entities, relationships).
        """
        entities: list[GraphEntity] = []
        relationships: list[GraphRelationship] = []

        fm = extract_frontmatter(content)
        body = body_after_frontmatter(content)

        # 1. Note entity (every note becomes a node)
        note_name = fm.get("title") or _slug_from_path(rel_path)
        note_type = _TYPE_MAP.get(fm.get("type", ""), "note")
        note_entity = GraphEntity(
            name=note_name,
            entity_type=note_type,
            source_path=rel_path,
            properties={k: v for k, v in fm.items() if k in ("type", "status", "captured_at")},
        )
        entities.append(note_entity)

        # 2. Tags → tag entities + tagged_with relationships
        raw_tags = fm.get("tags") or []
        if isinstance(raw_tags, str):
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        elif isinstance(raw_tags, list):
            tags = [str(t).strip() for t in raw_tags if t]
        else:
            tags = []
        for tag in tags:
            tag_entity = GraphEntity(name=tag, entity_type="tag", source_path=rel_path)
            entities.append(tag_entity)
            relationships.append(
                GraphRelationship(
                    source_id=note_entity.id,
                    target_id=tag_entity.id,
                    rel_type="tagged_with",
                    source_path=rel_path,
                )
            )

        # 3. Source → source entity + created_by relationship
        source = fm.get("source")
        if source and isinstance(source, str):
            source_entity = GraphEntity(name=source, entity_type="source", source_path=rel_path)
            entities.append(source_entity)
            relationships.append(
                GraphRelationship(
                    source_id=note_entity.id,
                    target_id=source_entity.id,
                    rel_type="created_by",
                    source_path=rel_path,
                )
            )

        # 4. Related wikilinks → related_to relationships
        related = fm.get("related") or []
        if isinstance(related, str):
            related = WIKILINK_RE.findall(related)
        elif isinstance(related, list):
            # Extract from wikilink strings like "[[note-title]]"
            extracted: list[str] = []
            for item in related:
                if isinstance(item, str):
                    found = WIKILINK_RE.findall(item)
                    extracted.extend(found if found else [item])
            related = extracted

        for target_name in related:
            target_entity = GraphEntity(name=target_name, entity_type="note", source_path=rel_path)
            entities.append(target_entity)
            relationships.append(
                GraphRelationship(
                    source_id=note_entity.id,
                    target_id=target_entity.id,
                    rel_type="related_to",
                    source_path=rel_path,
                )
            )

        # 5. Body wikilinks → references relationships
        body_links = WIKILINK_RE.findall(body)
        # Deduplicate and exclude already-captured related links
        related_set = set(related)
        seen: set[str] = set()
        for link_name in body_links:
            if link_name in related_set or link_name in seen:
                continue
            seen.add(link_name)
            link_entity = GraphEntity(name=link_name, entity_type="note", source_path=rel_path)
            entities.append(link_entity)
            relationships.append(
                GraphRelationship(
                    source_id=note_entity.id,
                    target_id=link_entity.id,
                    rel_type="references",
                    source_path=rel_path,
                )
            )

        logger.debug(
            "graph_extracted",
            path=rel_path,
            entities=len(entities),
            relationships=len(relationships),
        )
        return entities, relationships

    async def extract_with_llm(
        self, rel_path: str, content: str
    ) -> tuple[list[GraphEntity], list[GraphRelationship]]:
        """Extract using rules first, then enhance with LLM if available.

        Returns combined results from both rule-based and LLM extraction.
        """
        entities, relationships = self.extract_from_note(rel_path, content)

        if self._llm_extractor is not None:
            body = body_after_frontmatter(content)
            llm_entities, llm_rels = await self._llm_extractor.extract(rel_path, body)
            entities.extend(llm_entities)
            relationships.extend(llm_rels)

        return entities, relationships
