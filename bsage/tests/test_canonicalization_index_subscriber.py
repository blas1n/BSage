"""Tests for CanonicalizationIndexSubscriber (Class_Diagram §10.2)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bsage.core.events import Event, EventBus, EventType
from bsage.garden.canonicalization import models
from bsage.garden.canonicalization.index import InMemoryCanonicalizationIndex
from bsage.garden.canonicalization.index_subscriber import (
    CanonicalizationIndexSubscriber,
)
from bsage.garden.canonicalization.store import NoteStore
from bsage.garden.storage import FileSystemStorage


@pytest.fixture
def storage(tmp_path: Path) -> FileSystemStorage:
    return FileSystemStorage(tmp_path)


@pytest.fixture
async def index(storage: FileSystemStorage) -> InMemoryCanonicalizationIndex:
    idx = InMemoryCanonicalizationIndex()
    await idx.initialize(storage)
    return idx


@pytest.fixture
def store(storage: FileSystemStorage) -> NoteStore:
    return NoteStore(storage)


class TestCanonicalEventInvalidates:
    @pytest.mark.asyncio
    async def test_action_drafted_event_pulls_in_action(
        self,
        index: InMemoryCanonicalizationIndex,
        store: NoteStore,
        storage: FileSystemStorage,
    ) -> None:
        # Subscriber wired
        sub = CanonicalizationIndexSubscriber(index)

        # Create the action note on disk WITHOUT calling index.invalidate
        path = "actions/create-concept/20260507-140000-ml.md"
        await store.write_action(
            models.ActionEntry(
                path=path,
                kind="create-concept",
                status="draft",
                action_schema_version="create-concept-v1",
                params={"concept": "ml", "title": "ML"},
                created_at=datetime(2026, 5, 7),
                updated_at=datetime(2026, 5, 7),
                expires_at=datetime(2026, 5, 8),
            )
        )
        # Index hasn't seen it yet
        assert (await index.list_actions(kind="create-concept")) == []

        # Subscriber receives the event → invalidates
        await sub.on_event(
            Event(
                event_type=EventType.CANONICALIZATION_ACTION_DRAFTED,
                payload={"path": path, "kind": "create-concept", "status": "draft"},
            )
        )
        actions = await index.list_actions(kind="create-concept")
        assert len(actions) == 1
        assert actions[0].path == path

    @pytest.mark.asyncio
    async def test_action_applied_event_invalidates_each_affected_path(
        self,
        index: InMemoryCanonicalizationIndex,
        store: NoteStore,
        storage: FileSystemStorage,
    ) -> None:
        # Apply has already mutated disk: write a concept directly
        await store.write_concept(
            models.ConceptEntry(
                concept_id="ml",
                path="concepts/active/ml.md",
                display="ML",
                aliases=[],
                created_at=datetime(2026, 5, 7),
                updated_at=datetime(2026, 5, 7),
            )
        )
        sub = CanonicalizationIndexSubscriber(index)
        await sub.on_event(
            Event(
                event_type=EventType.CANONICALIZATION_ACTION_APPLIED,
                payload={
                    "action_path": "actions/create-concept/x.md",
                    "affected_paths": [
                        "actions/create-concept/x.md",
                        "concepts/active/ml.md",
                    ],
                },
            )
        )
        # Concept is now indexed
        assert await index.get_active_concept("ml") is not None


class TestNoteUpdatedFiltering:
    @pytest.mark.asyncio
    async def test_canon_path_invalidates(
        self,
        index: InMemoryCanonicalizationIndex,
        store: NoteStore,
    ) -> None:
        await store.write_concept(
            models.ConceptEntry(
                concept_id="ml",
                path="concepts/active/ml.md",
                display="ML",
                aliases=[],
                created_at=datetime(2026, 5, 7),
                updated_at=datetime(2026, 5, 7),
            )
        )
        sub = CanonicalizationIndexSubscriber(index)
        await sub.on_event(
            Event(
                event_type=EventType.NOTE_UPDATED,
                payload={"path": "concepts/active/ml.md"},
            )
        )
        assert await index.get_active_concept("ml") is not None

    @pytest.mark.asyncio
    async def test_non_canon_path_ignored(self, index: InMemoryCanonicalizationIndex) -> None:
        # Garden path NOTE_UPDATED — subscriber does nothing.
        sub = CanonicalizationIndexSubscriber(index)
        # Patch invalidate to assert it isn't called
        index.invalidate = AsyncMock()  # type: ignore[method-assign]
        await sub.on_event(
            Event(
                event_type=EventType.NOTE_UPDATED,
                payload={"path": "garden/seedling/foo.md"},
            )
        )
        index.invalidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_unrelated_event_ignored(self, index: InMemoryCanonicalizationIndex) -> None:
        sub = CanonicalizationIndexSubscriber(index)
        index.invalidate = AsyncMock()  # type: ignore[method-assign]
        await sub.on_event(Event(event_type=EventType.PLUGIN_RUN_START, payload={"name": "x"}))
        index.invalidate.assert_not_called()


class TestEventBusIntegration:
    @pytest.mark.asyncio
    async def test_subscriber_picks_up_canon_event_through_bus(
        self,
        index: InMemoryCanonicalizationIndex,
        store: NoteStore,
    ) -> None:
        bus = EventBus()
        bus.subscribe(CanonicalizationIndexSubscriber(index))

        # Write disk; emit event; subscriber should reload.
        await store.write_concept(
            models.ConceptEntry(
                concept_id="ml",
                path="concepts/active/ml.md",
                display="ML",
                aliases=["machine-learning"],
                created_at=datetime(2026, 5, 7),
                updated_at=datetime(2026, 5, 7),
            )
        )
        assert await index.get_active_concept("ml") is None  # not yet indexed

        await bus.emit(
            Event(
                event_type=EventType.CANONICALIZATION_ACTION_APPLIED,
                payload={
                    "action_path": "actions/create-concept/x.md",
                    "affected_paths": ["concepts/active/ml.md"],
                },
            )
        )
        entry = await index.get_active_concept("ml")
        assert entry is not None
        assert "machine-learning" in entry.aliases


class TestPathExtraction:
    def test_filters_non_canon_paths_from_affected(self) -> None:
        # A merge-concepts ACTION_APPLIED carries garden paths too — the
        # subscriber's job is to invalidate ONLY canon-rooted paths.
        out = CanonicalizationIndexSubscriber._extract_canon_paths(
            {
                "action_path": "actions/merge-concepts/x.md",
                "affected_paths": [
                    "actions/merge-concepts/x.md",
                    "concepts/active/ml.md",
                    "concepts/merged/m-l.md",
                    "garden/seedling/foo.md",  # NOT canon — must be excluded
                ],
            }
        )
        assert "garden/seedling/foo.md" not in out
        assert "concepts/active/ml.md" in out
        assert "concepts/merged/m-l.md" in out
        assert "actions/merge-concepts/x.md" in out

    def test_dedups_repeated_paths(self) -> None:
        out = CanonicalizationIndexSubscriber._extract_canon_paths(
            {
                "path": "actions/create-concept/x.md",
                "action_path": "actions/create-concept/x.md",
                "affected_paths": ["actions/create-concept/x.md"],
            }
        )
        assert out == ["actions/create-concept/x.md"]
