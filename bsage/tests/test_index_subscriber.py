"""Tests for bsage.garden.index_subscriber — EventBus-driven note indexing."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from bsage.core.events import Event, EventType
from bsage.garden.index_subscriber import IndexSubscriber


def _make_retriever():
    retriever = AsyncMock()
    retriever.index_note = AsyncMock()
    return retriever


def _make_vault(root: Path = Path("/vault"), content: str = "note content"):
    vault = MagicMock()
    vault.root = root
    vault.read_note_content = AsyncMock(return_value=content)
    return vault


class TestIndexSubscriber:
    """Test IndexSubscriber event handling."""

    async def test_indexes_on_seed_written(self) -> None:
        retriever = _make_retriever()
        vault = _make_vault()

        sub = IndexSubscriber(retriever, vault)
        event = Event(
            event_type=EventType.SEED_WRITTEN,
            payload={"path": "/vault/seeds/chat/2026-02-27_0900.md", "source": "chat"},
        )
        await sub.on_event(event)

        retriever.index_note.assert_called_once_with(
            "seeds/chat/2026-02-27_0900.md", "note content"
        )

    async def test_indexes_on_garden_written(self) -> None:
        retriever = _make_retriever()
        vault = _make_vault()

        sub = IndexSubscriber(retriever, vault)
        event = Event(
            event_type=EventType.GARDEN_WRITTEN,
            payload={"path": "/vault/garden/idea/my-note.md", "source": "test"},
        )
        await sub.on_event(event)

        retriever.index_note.assert_called_once_with("garden/idea/my-note.md", "note content")

    async def test_ignores_other_events(self) -> None:
        retriever = _make_retriever()
        vault = _make_vault()

        sub = IndexSubscriber(retriever, vault)
        event = Event(
            event_type=EventType.ACTION_LOGGED,
            payload={"path": "/vault/actions/2026-02-27.md"},
        )
        await sub.on_event(event)

        retriever.index_note.assert_not_called()

    async def test_ignores_empty_path(self) -> None:
        retriever = _make_retriever()
        vault = _make_vault()

        sub = IndexSubscriber(retriever, vault)
        event = Event(
            event_type=EventType.SEED_WRITTEN,
            payload={"source": "chat"},  # no "path"
        )
        await sub.on_event(event)

        retriever.index_note.assert_not_called()

    async def test_handles_read_error_gracefully(self) -> None:
        retriever = _make_retriever()
        vault = _make_vault()
        vault.read_note_content = AsyncMock(side_effect=OSError("read error"))

        sub = IndexSubscriber(retriever, vault)
        event = Event(
            event_type=EventType.SEED_WRITTEN,
            payload={"path": "/vault/seeds/chat/note.md"},
        )
        # Should not raise
        await sub.on_event(event)
        retriever.index_note.assert_not_called()
