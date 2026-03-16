"""Tests for VectorSubscriber — embedding computation on vault events."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.events import Event, EventType
from bsage.garden.vault import Vault
from bsage.garden.vector_subscriber import VectorSubscriber


@pytest.fixture()
def vault(tmp_path: Path) -> Vault:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    return Vault(vault_root)


@pytest.fixture()
def mock_vector_store():
    store = AsyncMock()
    store.store = AsyncMock()
    store.remove = AsyncMock()
    return store


@pytest.fixture()
def mock_embedder():
    embedder = MagicMock()
    embedder.enabled = True
    embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    return embedder


def _write_note(vault: Vault, rel_path: str, content: str) -> Path:
    abs_path = vault.resolve_path(rel_path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content)
    return abs_path


class TestVectorSubscriber:
    async def test_embeds_on_garden_written(self, vault, mock_vector_store, mock_embedder) -> None:
        _write_note(vault, "garden/idea/test.md", "---\ntitle: Test\n---\nSome body.")
        sub = VectorSubscriber(mock_vector_store, vault, mock_embedder)

        event = Event(
            event_type=EventType.GARDEN_WRITTEN,
            payload={"path": "garden/idea/test.md"},
        )
        await sub.on_event(event)

        mock_embedder.embed.assert_awaited_once()
        mock_vector_store.store.assert_awaited_once()
        call_args = mock_vector_store.store.call_args
        assert call_args[0][0] == "garden/idea/test.md"
        assert call_args[0][1] == [0.1, 0.2, 0.3]

    async def test_embeds_on_seed_written(self, vault, mock_vector_store, mock_embedder) -> None:
        _write_note(vault, "seeds/test/2026.md", "---\ntype: seed\n---\nRaw data.")
        sub = VectorSubscriber(mock_vector_store, vault, mock_embedder)

        event = Event(
            event_type=EventType.SEED_WRITTEN,
            payload={"path": "seeds/test/2026.md"},
        )
        await sub.on_event(event)

        mock_embedder.embed.assert_awaited_once()
        mock_vector_store.store.assert_awaited_once()

    async def test_embeds_on_note_updated(self, vault, mock_vector_store, mock_embedder) -> None:
        _write_note(vault, "garden/idea/test.md", "---\ntitle: Updated\n---\nNew body.")
        sub = VectorSubscriber(mock_vector_store, vault, mock_embedder)

        event = Event(
            event_type=EventType.NOTE_UPDATED,
            payload={"path": "garden/idea/test.md"},
        )
        await sub.on_event(event)

        mock_embedder.embed.assert_awaited_once()

    async def test_removes_on_note_deleted(self, vault, mock_vector_store, mock_embedder) -> None:
        sub = VectorSubscriber(mock_vector_store, vault, mock_embedder)

        event = Event(
            event_type=EventType.NOTE_DELETED,
            payload={"path": "garden/idea/test.md"},
        )
        await sub.on_event(event)

        mock_vector_store.remove.assert_awaited_once_with("garden/idea/test.md")
        mock_embedder.embed.assert_not_awaited()

    async def test_ignores_irrelevant_events(self, vault, mock_vector_store, mock_embedder) -> None:
        sub = VectorSubscriber(mock_vector_store, vault, mock_embedder)

        event = Event(
            event_type=EventType.ACTION_LOGGED,
            payload={"path": "actions/2026.md"},
        )
        await sub.on_event(event)

        mock_embedder.embed.assert_not_awaited()
        mock_vector_store.store.assert_not_awaited()

    async def test_handles_missing_file_gracefully(
        self, vault, mock_vector_store, mock_embedder
    ) -> None:
        sub = VectorSubscriber(mock_vector_store, vault, mock_embedder)

        event = Event(
            event_type=EventType.GARDEN_WRITTEN,
            payload={"path": "garden/idea/nonexistent.md"},
        )
        await sub.on_event(event)

        mock_embedder.embed.assert_not_awaited()

    async def test_handles_embed_failure(self, vault, mock_vector_store, mock_embedder) -> None:
        _write_note(vault, "garden/idea/test.md", "---\ntitle: Fail\n---\nBody.")
        mock_embedder.embed = AsyncMock(side_effect=RuntimeError("API down"))
        sub = VectorSubscriber(mock_vector_store, vault, mock_embedder)

        event = Event(
            event_type=EventType.GARDEN_WRITTEN,
            payload={"path": "garden/idea/test.md"},
        )
        await sub.on_event(event)

        mock_vector_store.store.assert_not_awaited()
