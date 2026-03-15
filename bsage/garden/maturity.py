"""Note maturity lifecycle — status constants and promotion evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from bsage.core.skill_context import GraphInterface

logger = structlog.get_logger(__name__)


class NoteMaturity(StrEnum):
    """Garden note maturity stages, ordered from youngest to most mature."""

    SEED = "seed"
    SEEDLING = "seedling"
    BUDDING = "budding"
    EVERGREEN = "evergreen"


MATURITY_ORDER: list[NoteMaturity] = [
    NoteMaturity.SEED,
    NoteMaturity.SEEDLING,
    NoteMaturity.BUDDING,
    NoteMaturity.EVERGREEN,
]

# Legacy status mapping
_LEGACY_MAP: dict[str, NoteMaturity] = {
    "growing": NoteMaturity.SEED,
}


def normalize_status(status: str) -> NoteMaturity:
    """Normalize a status string to a NoteMaturity value.

    Maps legacy values (e.g. ``growing``) to their canonical equivalents
    and falls back to ``SEED`` for unknown statuses.
    """
    if status in _LEGACY_MAP:
        return _LEGACY_MAP[status]
    try:
        return NoteMaturity(status)
    except ValueError:
        return NoteMaturity.SEED


@dataclass
class MaturityConfig:
    """Configurable thresholds for maturity promotion."""

    seedling_min_relationships: int = 2
    budding_min_sources: int = 3
    evergreen_min_days_stable: int = 14
    evergreen_min_relationships: int = 5


class MaturityEvaluator:
    """Evaluates garden notes for maturity promotion based on graph metrics."""

    def __init__(self, graph: GraphInterface, config: MaturityConfig) -> None:
        self._graph = graph
        self._config = config

    async def evaluate(self, note_path: str, current_status: str) -> NoteMaturity | None:
        """Evaluate whether a note should be promoted.

        Args:
            note_path: Relative vault path of the note (e.g. ``garden/idea/foo.md``).
            current_status: Current status string from the note's frontmatter.

        Returns:
            The new maturity level if promotion is warranted, or ``None``.
        """
        status = normalize_status(current_status)
        idx = MATURITY_ORDER.index(status)

        if idx >= len(MATURITY_ORDER) - 1:
            return None  # already evergreen

        if status == NoteMaturity.SEED:
            return await self._check_seed_to_seedling(note_path)
        if status == NoteMaturity.SEEDLING:
            return await self._check_seedling_to_budding(note_path)
        if status == NoteMaturity.BUDDING:
            return await self._check_budding_to_evergreen(note_path)

        return None

    async def _check_seed_to_seedling(self, note_path: str) -> NoteMaturity | None:
        rel_count = await self._graph.count_relationships_for_entity(note_path)
        if rel_count >= self._config.seedling_min_relationships:
            return NoteMaturity.SEEDLING
        return None

    async def _check_seedling_to_budding(self, note_path: str) -> NoteMaturity | None:
        source_count = await self._graph.count_distinct_sources(note_path)
        if source_count >= self._config.budding_min_sources:
            return NoteMaturity.BUDDING
        return None

    async def _check_budding_to_evergreen(self, note_path: str) -> NoteMaturity | None:
        updated_at = await self._graph.get_entity_updated_at(note_path)
        if updated_at is None:
            return None

        try:
            last_update = datetime.fromisoformat(updated_at).replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return None

        days_stable = (datetime.now(tz=UTC) - last_update).days
        if days_stable < self._config.evergreen_min_days_stable:
            return None

        rel_count = await self._graph.count_relationships_for_entity(note_path)
        if rel_count >= self._config.evergreen_min_relationships:
            return NoteMaturity.EVERGREEN
        return None
