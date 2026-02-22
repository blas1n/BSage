"""Tests for bsage.garden.writer — GardenWriter and GardenNote."""

from pathlib import Path

import pytest

from bsage.garden.vault import Vault
from bsage.garden.writer import GardenNote, GardenWriter


class TestGardenNote:
    """Test GardenNote dataclass."""

    def test_garden_note_defaults(self) -> None:
        """GardenNote should have empty defaults for related and tags."""
        note = GardenNote(
            title="Test Note",
            content="Some content",
            note_type="idea",
            source="test-skill",
        )
        assert note.title == "Test Note"
        assert note.related == []
        assert note.tags == []


class TestWriteSeed:
    """Test GardenWriter.write_seed creates files with frontmatter."""

    @pytest.mark.asyncio
    async def test_write_seed_creates_file_with_frontmatter(self, tmp_path: Path) -> None:
        """write_seed should create a markdown file with YAML frontmatter."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        data = {"summary": "Team standup", "attendees": ["Alice", "Bob"]}
        result = await writer.write_seed("calendar", data)

        assert result.exists()
        assert result.suffix == ".md"

        content = result.read_text()
        assert content.startswith("---\n")
        assert "type: seed" in content
        assert "source: calendar" in content
        assert "captured_at:" in content
        assert "---" in content.split("---\n", 2)[2] or content.count("---") >= 2

    @pytest.mark.asyncio
    async def test_write_seed_creates_source_subdirectory(self, tmp_path: Path) -> None:
        """write_seed should create the seeds/{source}/ directory if it doesn't exist."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        data = {"event": "meeting"}
        result = await writer.write_seed("google-calendar", data)

        assert (tmp_path / "seeds" / "google-calendar").is_dir()
        assert result.parent == tmp_path / "seeds" / "google-calendar"

    @pytest.mark.asyncio
    async def test_write_seed_contains_data(self, tmp_path: Path) -> None:
        """write_seed should include the data in the file body."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        data = {"summary": "Important meeting", "location": "Room 42"}
        result = await writer.write_seed("calendar", data)

        content = result.read_text()
        assert "summary" in content
        assert "Important meeting" in content


class TestWriteGarden:
    """Test GardenWriter.write_garden creates notes with frontmatter."""

    @pytest.mark.asyncio
    async def test_write_garden_creates_note_with_frontmatter(self, tmp_path: Path) -> None:
        """write_garden should create a note in garden/{note_type}/ with frontmatter."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        note = GardenNote(
            title="My Great Idea",
            content="This is an idea about something.",
            note_type="idea",
            source="garden-writer",
            related=["BSage"],
        )
        result = await writer.write_garden(note)

        assert result.exists()
        assert result.parent == tmp_path / "garden" / "idea"

        content = result.read_text()
        assert content.startswith("---\n")
        assert "type: idea" in content
        assert "status: growing" in content
        assert "source: garden-writer" in content
        assert "captured_at:" in content
        assert "[[BSage]]" in content
        assert "This is an idea about something." in content

    @pytest.mark.asyncio
    async def test_write_garden_slug_from_title(self, tmp_path: Path) -> None:
        """write_garden should generate a slug from the title."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        note = GardenNote(
            title="My Great Idea",
            content="Content here.",
            note_type="idea",
            source="test",
        )
        result = await writer.write_garden(note)

        assert result.name == "my-great-idea.md"

    @pytest.mark.asyncio
    async def test_write_garden_dedup_with_timestamp_suffix(self, tmp_path: Path) -> None:
        """Writing the same slug twice should create slug.md then slug_001.md."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        note = GardenNote(
            title="Duplicate Idea",
            content="First version.",
            note_type="idea",
            source="test",
        )

        first = await writer.write_garden(note)
        assert first.name == "duplicate-idea.md"

        note2 = GardenNote(
            title="Duplicate Idea",
            content="Second version.",
            note_type="idea",
            source="test",
        )
        second = await writer.write_garden(note2)
        assert second.name == "duplicate-idea_001.md"

        note3 = GardenNote(
            title="Duplicate Idea",
            content="Third version.",
            note_type="idea",
            source="test",
        )
        third = await writer.write_garden(note3)
        assert third.name == "duplicate-idea_002.md"

    @pytest.mark.asyncio
    async def test_write_garden_special_chars_in_title(self, tmp_path: Path) -> None:
        """write_garden should handle special characters in titles."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        note = GardenNote(
            title="Hello, World! (2026)",
            content="Content.",
            note_type="idea",
            source="test",
        )
        result = await writer.write_garden(note)

        # Slug should be lowercase, hyphens, no special chars
        assert result.name == "hello-world-2026.md"


class TestWriteAction:
    """Test GardenWriter.write_action appends to daily log."""

    @pytest.mark.asyncio
    async def test_write_action_appends_to_daily_log(self, tmp_path: Path) -> None:
        """write_action should append an entry with timestamp and skill name."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        await writer.write_action("garden-writer", "Processed 3 notes")

        actions_dir = tmp_path / "actions"
        md_files = list(actions_dir.glob("*.md"))
        assert len(md_files) == 1

        content = md_files[0].read_text()
        assert "garden-writer" in content
        assert "Processed 3 notes" in content

    @pytest.mark.asyncio
    async def test_write_action_creates_actions_dir_if_missing(self, tmp_path: Path) -> None:
        """write_action should handle missing actions/ directory gracefully."""
        vault = Vault(tmp_path)
        # Intentionally NOT calling ensure_dirs — actions/ doesn't exist
        writer = GardenWriter(vault)

        await writer.write_action("test-skill", "Action summary")

        actions_dir = tmp_path / "actions"
        assert actions_dir.is_dir()
        md_files = list(actions_dir.glob("*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text()
        assert "test-skill" in content

    @pytest.mark.asyncio
    async def test_write_action_appends_multiple_entries(self, tmp_path: Path) -> None:
        """Multiple write_action calls on the same day append to the same file."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        await writer.write_action("skill-a", "First action")
        await writer.write_action("skill-b", "Second action")

        actions_dir = tmp_path / "actions"
        md_files = list(actions_dir.glob("*.md"))
        assert len(md_files) == 1

        content = md_files[0].read_text()
        assert "skill-a" in content
        assert "First action" in content
        assert "skill-b" in content
        assert "Second action" in content


class TestReadNotes:
    """Test GardenWriter.read_notes delegates to vault."""

    @pytest.mark.asyncio
    async def test_read_notes_delegates_to_vault(self, tmp_path: Path) -> None:
        """read_notes should delegate to vault's read_notes method."""
        vault = Vault(tmp_path)
        notes_dir = tmp_path / "garden" / "ideas"
        notes_dir.mkdir(parents=True)
        (notes_dir / "note-a.md").write_text("# Note A")
        (notes_dir / "note-b.md").write_text("# Note B")

        writer = GardenWriter(vault)
        result = await writer.read_notes("garden/ideas")

        assert len(result) == 2
        assert result[0].name == "note-a.md"
        assert result[1].name == "note-b.md"
