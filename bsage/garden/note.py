"""GardenNote dataclass and frontmatter / slug helpers.

Split out of ``bsage/garden/writer.py`` (M15, Hardening Sprint 2) so that the
pure-data layer can be imported without dragging the full ``GardenWriter``
implementation. ``writer.py`` re-exports these symbols for backwards
compatibility — existing call sites keep working unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import yaml

_VALID_NOTE_TYPES: frozenset[str] = frozenset(
    {"idea", "insight", "project", "event", "task", "fact", "person", "preference"}
)
"""Note types that ``GardenWriter.handle_write_note`` accepts as-is.

Other values are silently coerced to ``"idea"`` for compatibility with older
tool-call payloads.
"""


_MAX_ACTION_SUMMARY: int = 200
"""Cap on action-log summary length before truncation with an ellipsis."""


@dataclass
class GardenNote:
    """Structured representation of a garden note (v2.2).

    Attributes:
        title: Human-readable title for the note.
        content: Markdown body content.
        note_type: Entity type (idea / insight / project / event / task / fact / etc.).
        source: Name of the skill or source that created this note.
        related: List of untyped related note titles for ``related:`` field.
        tags: List of tags for categorization.
        confidence: Content confidence score (0.0-1.0).
        knowledge_layer: Knowledge layer classification.
        relations: Typed relations dict — key is relation type, value is list of targets.
                   Example: {"attendees": ["[[Alice]]"], "belongs_to": ["[[Project X]]"]}
        aliases: Alternative names for Obsidian search.
        extra_fields: Additional frontmatter fields for specialized note types
                      (fact: subject/predicate/object/valid_from/valid_to/supersedes/source_type,
                       preference: subject/domain/context/source_type).
    """

    title: str
    content: str
    note_type: str
    source: str
    related: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.9
    knowledge_layer: str = "semantic"
    relations: dict[str, list[str]] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    extra_fields: dict[str, Any] = field(default_factory=dict)
    # Phase 0 P0.5 — tenant isolation. None means "use writer default" (set by
    # GardenWriter from settings.default_tenant_id) so cron / local writes
    # don't 500. Authenticated route handlers MUST set this to the active
    # tenant_id from the principal.
    tenant_id: str | None = None


def slugify(title: str) -> str:
    """Convert a title to a URL-friendly slug.

    Lowercase, replace spaces with hyphens, remove special characters.
    Preserves Unicode word characters (Korean, Japanese, Chinese, etc.).
    Falls back to a timestamp when the result would be empty.
    """
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    if not slug:
        slug = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    return slug


def build_frontmatter(metadata: dict) -> str:
    """Build YAML frontmatter block from a dict."""
    dumped = yaml.dump(metadata, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n"


# ---------------------------------------------------------------------------
# Internal aliases — preserved so `from bsage.garden.writer import _slugify`
# continues to work for any external consumer that imported the private name.
# ---------------------------------------------------------------------------
_slugify = slugify
_build_frontmatter = build_frontmatter

__all__ = [
    "GardenNote",
    "_MAX_ACTION_SUMMARY",
    "_VALID_NOTE_TYPES",
    "_build_frontmatter",
    "_slugify",
    "build_frontmatter",
    "slugify",
]
