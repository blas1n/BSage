"""Tests for auto-generated vault catalog (Karpathy-style index.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bsage.garden.file_index_reader import FileIndexReader
from bsage.garden.vault import Vault
from bsage.garden.writer import GardenNote, GardenWriter


class TestWriteCatalog:
    """Test FileIndexReader.write_catalog() generates a human-readable index.md."""

    @pytest.fixture()
    def vault_and_reader(self, tmp_path: Path) -> tuple[Vault, FileIndexReader, GardenWriter]:
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        reader = FileIndexReader(vault=vault)
        writer = GardenWriter(vault)
        return vault, reader, writer

    @pytest.mark.asyncio
    async def test_write_catalog_creates_index_md(
        self, vault_and_reader: tuple[Vault, FileIndexReader, GardenWriter]
    ) -> None:
        """write_catalog() should create index.md at vault root."""
        vault, reader, writer = vault_and_reader

        await writer.write_garden(
            GardenNote(title="Test Note", content="Hello", note_type="idea", source="test")
        )
        await reader.rebuild_all()
        await reader.write_catalog()

        index_path = vault.root / "index.md"
        assert index_path.exists()

    @pytest.mark.asyncio
    async def test_catalog_contains_note_titles(
        self, vault_and_reader: tuple[Vault, FileIndexReader, GardenWriter]
    ) -> None:
        """Catalog should list note titles as wikilinks."""
        vault, reader, writer = vault_and_reader

        await writer.write_garden(
            GardenNote(title="AI Overview", content="About AI", note_type="insight", source="test")
        )
        await writer.write_garden(
            GardenNote(
                title="Machine Learning",
                content="About ML",
                note_type="idea",
                source="test",
            )
        )
        await reader.rebuild_all()
        await reader.write_catalog()

        content = (vault.root / "index.md").read_text()
        assert "[[AI Overview]]" in content
        assert "[[Machine Learning]]" in content

    @pytest.mark.asyncio
    async def test_catalog_groups_by_note_type(
        self, vault_and_reader: tuple[Vault, FileIndexReader, GardenWriter]
    ) -> None:
        """Catalog should group notes by their type (idea, insight, etc.)."""
        vault, reader, writer = vault_and_reader

        await writer.write_garden(
            GardenNote(title="Idea A", content="idea", note_type="idea", source="test")
        )
        await writer.write_garden(
            GardenNote(title="Insight B", content="insight", note_type="insight", source="test")
        )
        await reader.rebuild_all()
        await reader.write_catalog()

        content = (vault.root / "index.md").read_text()
        # Both type headers should appear
        assert "idea" in content.lower()
        assert "insight" in content.lower()

    @pytest.mark.asyncio
    async def test_catalog_includes_tags(
        self, vault_and_reader: tuple[Vault, FileIndexReader, GardenWriter]
    ) -> None:
        """Catalog should show tags for each note."""
        vault, reader, writer = vault_and_reader

        await writer.write_garden(
            GardenNote(
                title="Tagged Note",
                content="content",
                note_type="idea",
                source="test",
                tags=["ai", "research"],
            )
        )
        await reader.rebuild_all()
        await reader.write_catalog()

        content = (vault.root / "index.md").read_text()
        assert "#ai" in content
        assert "#research" in content

    @pytest.mark.asyncio
    async def test_catalog_has_header_and_count(
        self, vault_and_reader: tuple[Vault, FileIndexReader, GardenWriter]
    ) -> None:
        """Catalog should have a title header and total note count."""
        vault, reader, writer = vault_and_reader

        await writer.write_garden(
            GardenNote(title="Note 1", content="a", note_type="idea", source="test")
        )
        await writer.write_garden(
            GardenNote(title="Note 2", content="b", note_type="insight", source="test")
        )
        await reader.rebuild_all()
        await reader.write_catalog()

        content = (vault.root / "index.md").read_text()
        assert "# Knowledge Index" in content
        assert "2 notes" in content

    @pytest.mark.asyncio
    async def test_catalog_empty_vault(
        self, vault_and_reader: tuple[Vault, FileIndexReader, GardenWriter]
    ) -> None:
        """write_catalog() on empty vault should produce a valid file with 0 notes."""
        vault, reader, _ = vault_and_reader

        await reader.write_catalog()

        content = (vault.root / "index.md").read_text()
        assert "# Knowledge Index" in content
        assert "0 notes" in content
