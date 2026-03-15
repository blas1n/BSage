"""Tests for GraphSubscriber — EventBus integration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.events import Event, EventType
from bsage.garden.graph_models import GraphEntity, GraphRelationship
from bsage.garden.graph_subscriber import GraphSubscriber


@pytest.fixture
def vault_root(tmp_path):
    return tmp_path / "vault"


@pytest.fixture
def mock_vault(vault_root):
    vault = MagicMock()
    vault.root = vault_root
    vault.read_note_content = AsyncMock(
        return_value=(
            "---\ntype: idea\ntitle: Test Note\ntags: [ai]\n"
            "source: test-plugin\n---\nBody with [[Link]]."
        )
    )
    return vault


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.delete_by_source = AsyncMock(return_value=0)
    store.upsert_entity = AsyncMock(side_effect=lambda e: e.id)
    store.upsert_relationship = AsyncMock(return_value="rel-id")
    store.commit = AsyncMock()
    return store


@pytest.fixture
def mock_extractor():
    extractor = MagicMock()
    entity = GraphEntity(name="Test", entity_type="note", source_path="garden/idea/test.md")
    rel = GraphRelationship(
        source_id=entity.id,
        target_id="target-id",
        rel_type="references",
        source_path="garden/idea/test.md",
    )
    extractor.extract_from_note.return_value = ([entity], [rel])
    return extractor


@pytest.fixture
def subscriber(mock_store, mock_vault, mock_extractor):
    return GraphSubscriber(mock_store, mock_vault, mock_extractor)


async def test_seed_written_event(subscriber, mock_store, mock_vault, vault_root):
    note_path = vault_root / "seeds" / "test" / "note.md"
    event = Event(
        event_type=EventType.SEED_WRITTEN,
        payload={"path": str(note_path)},
    )

    await subscriber.on_event(event)

    mock_vault.read_note_content.assert_awaited_once_with(note_path)
    mock_store.delete_by_source.assert_awaited()
    mock_store.upsert_entity.assert_awaited()
    mock_store.upsert_relationship.assert_awaited()


async def test_garden_written_event(subscriber, mock_store, mock_vault, vault_root):
    note_path = vault_root / "garden" / "idea" / "test.md"
    event = Event(
        event_type=EventType.GARDEN_WRITTEN,
        payload={"path": str(note_path)},
    )

    await subscriber.on_event(event)

    mock_vault.read_note_content.assert_awaited_once()
    mock_store.upsert_entity.assert_awaited()


async def test_note_updated_event(subscriber, mock_store, mock_vault, vault_root):
    note_path = vault_root / "garden" / "idea" / "test.md"
    event = Event(
        event_type=EventType.NOTE_UPDATED,
        payload={"path": str(note_path)},
    )

    await subscriber.on_event(event)

    # Should delete old data then re-extract
    mock_store.delete_by_source.assert_awaited()
    mock_store.upsert_entity.assert_awaited()


async def test_note_deleted_event(subscriber, mock_store, vault_root):
    note_path = vault_root / "garden" / "idea" / "test.md"
    event = Event(
        event_type=EventType.NOTE_DELETED,
        payload={"path": str(note_path)},
    )

    await subscriber.on_event(event)

    mock_store.delete_by_source.assert_awaited_once()


async def test_irrelevant_event_ignored(subscriber, mock_store):
    event = Event(
        event_type=EventType.PLUGIN_RUN_START,
        payload={"name": "test"},
    )

    await subscriber.on_event(event)

    mock_store.upsert_entity.assert_not_awaited()
    mock_store.delete_by_source.assert_not_awaited()


async def test_empty_path_ignored(subscriber, mock_store):
    event = Event(
        event_type=EventType.SEED_WRITTEN,
        payload={},
    )

    await subscriber.on_event(event)

    mock_store.upsert_entity.assert_not_awaited()


async def test_entity_id_resolution(subscriber, mock_store, mock_vault, mock_extractor, vault_root):
    """Entity IDs in relationships are resolved to actual (possibly deduplicated) IDs."""
    entity_a = GraphEntity(name="A", entity_type="note", source_path="a.md", id="local-a")
    entity_b = GraphEntity(name="B", entity_type="note", source_path="a.md", id="local-b")
    rel = GraphRelationship(
        source_id="local-a", target_id="local-b", rel_type="related_to", source_path="a.md"
    )
    mock_extractor.extract_from_note.return_value = ([entity_a, entity_b], [rel])

    # Store returns different IDs (dedup scenario)
    mock_store.upsert_entity = AsyncMock(side_effect=["resolved-a", "resolved-b"])

    note_path = vault_root / "garden" / "idea" / "a.md"
    event = Event(
        event_type=EventType.GARDEN_WRITTEN,
        payload={"path": str(note_path)},
    )

    await subscriber.on_event(event)

    # Relationship should use resolved IDs
    call_args = mock_store.upsert_relationship.call_args[0][0]
    assert call_args.source_id == "resolved-a"
    assert call_args.target_id == "resolved-b"


async def test_read_failure_logged(subscriber, mock_store, mock_vault, vault_root):
    """Exceptions during content read are caught and logged."""
    mock_vault.read_note_content = AsyncMock(side_effect=FileNotFoundError("gone"))

    note_path = vault_root / "garden" / "idea" / "missing.md"
    event = Event(
        event_type=EventType.GARDEN_WRITTEN,
        payload={"path": str(note_path)},
    )

    # Should not raise
    await subscriber.on_event(event)

    mock_store.upsert_entity.assert_not_awaited()
