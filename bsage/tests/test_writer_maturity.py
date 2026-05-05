"""Tests for GardenWriter maturity lifecycle methods."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.events import EventType
from bsage.garden.vault import Vault
from bsage.garden.writer import GardenWriter


def _create_garden_note(vault_root: Path, subpath: str, status: str = "seed") -> Path:
    """Helper to create a garden note with given status."""
    note_path = vault_root / subpath
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\ntype: idea\nstatus: {status}\nsource: test\n---\n# Test\nContent.\n"
    )
    return note_path


@pytest.fixture()
def vault(tmp_path: Path) -> Vault:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    return Vault(vault_root)


@pytest.fixture()
def writer(vault: Vault) -> GardenWriter:
    return GardenWriter(vault)


class TestUpdateFrontmatterStatus:
    """Test GardenWriter.update_frontmatter_status()."""

    async def test_updates_status_field(self, vault: Vault, writer: GardenWriter) -> None:
        note = _create_garden_note(vault.root, "garden/idea/test.md", status="seed")
        await writer.update_frontmatter_status(note, "seedling")
        content = note.read_text()
        assert "status: seedling" in content
        assert "status: seed\n" not in content

    async def test_preserves_other_frontmatter(self, vault: Vault, writer: GardenWriter) -> None:
        note = _create_garden_note(vault.root, "garden/idea/test.md", status="seed")
        await writer.update_frontmatter_status(note, "budding")
        content = note.read_text()
        assert "type: idea" in content
        assert "source: test" in content
        assert "# Test" in content

    async def test_noop_when_status_missing(self, vault: Vault, writer: GardenWriter) -> None:
        note_path = vault.root / "garden" / "idea" / "no-status.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("---\ntype: idea\n---\n# No Status\n")
        await writer.update_frontmatter_status(note_path, "seedling")
        content = note_path.read_text()
        # Should not modify since no status field to replace
        assert "status:" not in content

    async def test_emits_note_updated_event(self, vault: Vault) -> None:
        event_bus = MagicMock()
        event_bus.emit = AsyncMock()
        writer = GardenWriter(vault, event_bus=event_bus)
        note = _create_garden_note(vault.root, "garden/idea/test.md", status="seed")
        await writer.update_frontmatter_status(note, "seedling")
        event_bus.emit.assert_called()
        call_args = event_bus.emit.call_args
        assert call_args[0][0].event_type == EventType.NOTE_UPDATED


class TestPromoteMaturity:
    """Test GardenWriter.promote_maturity()."""

    async def test_returns_empty_when_no_graph(self, writer: GardenWriter) -> None:
        result = await writer.promote_maturity(graph=None)
        assert result == {"promoted": 0, "checked": 0, "details": []}

    async def test_promotes_eligible_notes(self, vault: Vault, writer: GardenWriter) -> None:
        _create_garden_note(vault.root, "garden/idea/a.md", status="seed")
        _create_garden_note(vault.root, "garden/idea/b.md", status="seed")

        graph = AsyncMock()
        graph.count_relationships_for_entity = AsyncMock(return_value=3)
        graph.count_distinct_sources = AsyncMock(return_value=1)
        graph.get_entity_updated_at = AsyncMock(return_value=None)

        result = await writer.promote_maturity(graph)
        assert result["promoted"] == 2
        assert result["checked"] == 2
        assert len(result["details"]) == 2
        for detail in result["details"]:
            assert detail["from"] == "seed"
            assert detail["to"] == "seedling"

        # Verify files were updated
        for detail in result["details"]:
            note_path = vault.root / detail["path"]
            content = note_path.read_text()
            assert "status: seedling" in content

    async def test_skips_notes_not_eligible(self, vault: Vault, writer: GardenWriter) -> None:
        _create_garden_note(vault.root, "garden/idea/a.md", status="seed")

        graph = AsyncMock()
        graph.count_relationships_for_entity = AsyncMock(return_value=0)
        graph.count_distinct_sources = AsyncMock(return_value=0)
        graph.get_entity_updated_at = AsyncMock(return_value=None)

        result = await writer.promote_maturity(graph)
        assert result["promoted"] == 0
        assert result["checked"] == 1

    async def test_backward_compat_growing_status(self, vault: Vault, writer: GardenWriter) -> None:
        _create_garden_note(vault.root, "garden/idea/old.md", status="growing")

        graph = AsyncMock()
        graph.count_relationships_for_entity = AsyncMock(return_value=5)
        graph.count_distinct_sources = AsyncMock(return_value=1)
        graph.get_entity_updated_at = AsyncMock(return_value=None)

        result = await writer.promote_maturity(graph)
        assert result["promoted"] == 1
        assert result["details"][0]["from"] == "growing"
        assert result["details"][0]["to"] == "seedling"

    async def test_returns_empty_when_no_garden_dir(
        self, vault: Vault, writer: GardenWriter
    ) -> None:
        graph = AsyncMock()
        result = await writer.promote_maturity(graph)
        assert result["promoted"] == 0
        assert result["checked"] == 0

    async def test_promotion_moves_file_between_maturity_folders(
        self, vault: Vault, writer: GardenWriter
    ) -> None:
        """Step B3c: when maturity changes the file relocates from
        ``garden/seedling`` → ``garden/budding`` and the frontmatter
        ``maturity:`` field is rewritten."""
        path = vault.root / "garden" / "seedling" / "moving.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\nmaturity: seedling\nstatus: seedling\n---\n# Moving\nbody.\n",
            encoding="utf-8",
        )

        graph = AsyncMock()
        graph.count_relationships_for_entity = AsyncMock(return_value=4)
        graph.count_distinct_sources = AsyncMock(return_value=3)
        graph.get_entity_updated_at = AsyncMock(return_value=None)

        result = await writer.promote_maturity(graph)

        assert result["promoted"] == 1
        new_rel = result["details"][0]["path"]
        assert new_rel.startswith("garden/budding/")
        new_path = vault.root / new_rel
        assert new_path.exists()
        assert not path.exists()
        body = new_path.read_text()
        assert "maturity: budding" in body

    async def test_promotion_in_legacy_folder_updates_in_place(
        self, vault: Vault, writer: GardenWriter
    ) -> None:
        """Notes still living in legacy paths (``garden/idea/``...) are
        promoted via frontmatter only — the migration CLI handles the
        actual move so promote_maturity stays idempotent on unmigrated
        vaults."""
        legacy = _create_garden_note(vault.root, "garden/idea/legacy.md", status="seed")

        graph = AsyncMock()
        graph.count_relationships_for_entity = AsyncMock(return_value=3)
        graph.count_distinct_sources = AsyncMock(return_value=1)
        graph.get_entity_updated_at = AsyncMock(return_value=None)

        result = await writer.promote_maturity(graph)
        assert result["promoted"] == 1
        # File stayed put; only frontmatter changed.
        assert legacy.exists()
        body = legacy.read_text()
        assert "maturity: seedling" in body
