"""Tests for bsage.garden.index_subscriber — EventBus-driven index file updates."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from bsage.core.events import Event, EventType
from bsage.garden.index_subscriber import IndexSubscriber


def _make_index_reader():
    reader = AsyncMock()
    reader.index_note_from_content = AsyncMock()
    reader.remove_entry = AsyncMock()
    return reader


def _make_vault(root: Path = Path("/vault"), content: str = "note content"):
    vault = MagicMock()
    vault.root = root
    vault.read_note_content = AsyncMock(return_value=content)
    return vault


class TestIndexSubscriber:
    """Test IndexSubscriber event handling."""

    async def test_indexes_on_seed_written(self) -> None:
        index_reader = _make_index_reader()
        vault = _make_vault()

        sub = IndexSubscriber(index_reader, vault)
        event = Event(
            event_type=EventType.SEED_WRITTEN,
            payload={"path": "/vault/seeds/chat/2026-02-27_0900.md", "source": "chat"},
        )
        await sub.on_event(event)

        index_reader.index_note_from_content.assert_called_once_with(
            "seeds/chat/2026-02-27_0900.md", "note content"
        )

    async def test_indexes_on_garden_written(self) -> None:
        index_reader = _make_index_reader()
        vault = _make_vault()

        sub = IndexSubscriber(index_reader, vault)
        event = Event(
            event_type=EventType.GARDEN_WRITTEN,
            payload={"path": "/vault/garden/idea/my-note.md", "source": "test"},
        )
        await sub.on_event(event)

        index_reader.index_note_from_content.assert_called_once_with(
            "garden/idea/my-note.md", "note content"
        )

    async def test_ignores_other_events(self) -> None:
        index_reader = _make_index_reader()
        vault = _make_vault()

        sub = IndexSubscriber(index_reader, vault)
        event = Event(
            event_type=EventType.ACTION_LOGGED,
            payload={"path": "/vault/actions/2026-02-27.md"},
        )
        await sub.on_event(event)

        index_reader.index_note_from_content.assert_not_called()

    async def test_ignores_empty_path(self) -> None:
        index_reader = _make_index_reader()
        vault = _make_vault()

        sub = IndexSubscriber(index_reader, vault)
        event = Event(
            event_type=EventType.SEED_WRITTEN,
            payload={"source": "chat"},  # no "path"
        )
        await sub.on_event(event)

        index_reader.index_note_from_content.assert_not_called()

    async def test_handles_read_error_gracefully(self) -> None:
        index_reader = _make_index_reader()
        vault = _make_vault()
        vault.read_note_content = AsyncMock(side_effect=OSError("read error"))

        sub = IndexSubscriber(index_reader, vault)
        event = Event(
            event_type=EventType.SEED_WRITTEN,
            payload={"path": "/vault/seeds/chat/note.md"},
        )
        # Should not raise
        await sub.on_event(event)
        index_reader.index_note_from_content.assert_not_called()

    async def test_reindexes_on_note_updated(self) -> None:
        index_reader = _make_index_reader()
        vault = _make_vault(content="updated content")

        sub = IndexSubscriber(index_reader, vault)
        event = Event(
            event_type=EventType.NOTE_UPDATED,
            payload={"path": "/vault/garden/idea/my-note.md"},
        )
        await sub.on_event(event)

        index_reader.index_note_from_content.assert_called_once_with(
            "garden/idea/my-note.md", "updated content"
        )

    async def test_removes_on_note_deleted(self) -> None:
        index_reader = _make_index_reader()
        vault = _make_vault()

        sub = IndexSubscriber(index_reader, vault)
        event = Event(
            event_type=EventType.NOTE_DELETED,
            payload={"path": "/vault/garden/idea/deleted-note.md"},
        )
        await sub.on_event(event)

        index_reader.remove_entry.assert_called_once_with("garden/idea/deleted-note.md")

    async def test_note_deleted_ignores_empty_path(self) -> None:
        index_reader = _make_index_reader()
        vault = _make_vault()

        sub = IndexSubscriber(index_reader, vault)
        event = Event(
            event_type=EventType.NOTE_DELETED,
            payload={},
        )
        await sub.on_event(event)

        index_reader.remove_entry.assert_not_called()

    async def test_note_deleted_handles_error_gracefully(self) -> None:
        index_reader = _make_index_reader()
        index_reader.remove_entry = AsyncMock(side_effect=OSError("delete error"))
        vault = _make_vault()

        sub = IndexSubscriber(index_reader, vault)
        event = Event(
            event_type=EventType.NOTE_DELETED,
            payload={"path": "/vault/garden/idea/broken.md"},
        )
        # Should not raise
        await sub.on_event(event)
