"""Tests for bsage.garden.writer — GardenWriter and GardenNote."""

from pathlib import Path
from unittest.mock import AsyncMock, PropertyMock

import pytest

from bsage.garden.sync import SyncBackend, SyncManager, WriteEventType
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

    @pytest.mark.asyncio
    async def test_write_garden_unicode_title(self, tmp_path: Path) -> None:
        """write_garden should preserve Unicode characters in slugs."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        note = GardenNote(
            title="자동화의 자동화 프로젝트",
            content="한글 내용입니다.",
            note_type="idea",
            source="test",
        )
        result = await writer.write_garden(note)

        assert result.name == "자동화의-자동화-프로젝트.md"
        assert result.exists()
        content = result.read_text()
        assert "# 자동화의 자동화 프로젝트" in content

    @pytest.mark.asyncio
    async def test_write_garden_mixed_unicode_ascii_title(self, tmp_path: Path) -> None:
        """write_garden should handle titles with both Unicode and ASCII."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        note = GardenNote(
            title="harness-studio 컴포넌트 라이브러리",
            content="Mixed content.",
            note_type="idea",
            source="test",
        )
        result = await writer.write_garden(note)

        assert result.name == "harness-studio-컴포넌트-라이브러리.md"
        assert result.exists()


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

    @pytest.mark.asyncio
    async def test_write_action_truncates_long_summary(self, tmp_path: Path) -> None:
        """Long summaries should be truncated to _MAX_ACTION_SUMMARY chars."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        long_summary = "x" * 500
        await writer.write_action("test-skill", long_summary)

        actions_dir = tmp_path / "actions"
        content = list(actions_dir.glob("*.md"))[0].read_text()
        # The entry line should contain at most 200 x's + ellipsis, not 500
        assert "x" * 200 + "…" in content
        assert "x" * 201 not in content


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


def _make_sync_manager() -> tuple[SyncManager, AsyncMock]:
    """Create a SyncManager with one mock backend, return (manager, backend)."""
    mgr = SyncManager()
    backend = AsyncMock(spec=SyncBackend)
    type(backend).name = PropertyMock(return_value="test-backend")
    mgr.register(backend)
    return mgr, backend


class TestGardenWriterSync:
    """Test that GardenWriter notifies SyncManager after writes."""

    @pytest.mark.asyncio
    async def test_write_seed_notifies_sync(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        mgr, backend = _make_sync_manager()
        writer = GardenWriter(vault, sync_manager=mgr)

        await writer.write_seed("calendar", {"event": "test"})

        backend.sync.assert_called_once()
        event = backend.sync.call_args[0][0]
        assert event.event_type == WriteEventType.SEED
        assert event.source == "calendar"

    @pytest.mark.asyncio
    async def test_write_garden_notifies_sync(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        mgr, backend = _make_sync_manager()
        writer = GardenWriter(vault, sync_manager=mgr)

        note = GardenNote(
            title="Sync Test",
            content="Content.",
            note_type="idea",
            source="test-skill",
        )
        await writer.write_garden(note)

        backend.sync.assert_called_once()
        event = backend.sync.call_args[0][0]
        assert event.event_type == WriteEventType.GARDEN
        assert event.source == "test-skill"

    @pytest.mark.asyncio
    async def test_write_action_notifies_sync(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        mgr, backend = _make_sync_manager()
        writer = GardenWriter(vault, sync_manager=mgr)

        await writer.write_action("test-skill", "Did something")

        backend.sync.assert_called_once()
        event = backend.sync.call_args[0][0]
        assert event.event_type == WriteEventType.ACTION
        assert event.source == "test-skill"

    @pytest.mark.asyncio
    async def test_write_without_sync_manager(self, tmp_path: Path) -> None:
        """GardenWriter with no sync_manager should work exactly as before."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        result = await writer.write_seed("calendar", {"event": "test"})
        assert result.exists()

    @pytest.mark.asyncio
    async def test_write_garden_dict_notifies_sync(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        mgr, backend = _make_sync_manager()
        writer = GardenWriter(vault, sync_manager=mgr)

        await writer.write_garden(
            {
                "title": "Dict Note",
                "content": "From dict.",
                "note_type": "idea",
                "source": "dict-source",
            }
        )

        backend.sync.assert_called_once()
        event = backend.sync.call_args[0][0]
        assert event.source == "dict-source"


class TestHandleWriteNote:
    """Test GardenWriter.handle_write_note — LLM tool handler."""

    @pytest.mark.asyncio
    async def test_handle_write_note_calls_write_garden(self, tmp_path: Path) -> None:
        """handle_write_note should write a garden note and return result."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        result = await writer.handle_write_note(
            {"title": "Test Note", "content": "Body text", "tags": ["demo"]}
        )

        assert result["status"] == "saved"
        assert result["title"] == "Test Note"
        assert result["note_type"] == "idea"
        assert "path" in result
        assert Path(result["path"]).exists()

    @pytest.mark.asyncio
    async def test_handle_write_note_default_note_type(self, tmp_path: Path) -> None:
        """Omitting note_type should default to 'idea'."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        result = await writer.handle_write_note({"title": "Minimal", "content": "Body"})

        assert result["note_type"] == "idea"
        content = Path(result["path"]).read_text()
        assert "type: idea" in content

    @pytest.mark.asyncio
    async def test_handle_write_note_invalid_note_type_fallback(self, tmp_path: Path) -> None:
        """Invalid note_type should fall back to 'idea'."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        result = await writer.handle_write_note(
            {"title": "Bad Type", "content": "Body", "note_type": "invalid"}
        )

        assert result["note_type"] == "idea"

    @pytest.mark.asyncio
    async def test_handle_write_note_sets_source_to_chat(self, tmp_path: Path) -> None:
        """Source should always be 'chat'."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        result = await writer.handle_write_note({"title": "Source Test", "content": "Body"})

        content = Path(result["path"]).read_text()
        assert "source: chat" in content

    @pytest.mark.asyncio
    async def test_handle_write_note_empty_args(self, tmp_path: Path) -> None:
        """Empty args should produce an 'Untitled' note."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        result = await writer.handle_write_note({})

        assert result["title"] == "Untitled"
        assert result["status"] == "saved"


class TestHandleWriteSeed:
    """Test GardenWriter.handle_write_seed — LLM tool handler."""

    @pytest.mark.asyncio
    async def test_handle_write_seed_calls_write_seed(self, tmp_path: Path) -> None:
        """handle_write_seed should write a seed and return result."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        result = await writer.handle_write_seed({"source": "api-call", "data": {"key": "value"}})

        assert result["status"] == "saved"
        assert result["source"] == "api-call"
        assert "path" in result
        assert Path(result["path"]).exists()

    @pytest.mark.asyncio
    async def test_handle_write_seed_default_source(self, tmp_path: Path) -> None:
        """Omitting source should default to 'llm'."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        result = await writer.handle_write_seed({"data": {"x": 1}})

        assert result["source"] == "llm"

    @pytest.mark.asyncio
    async def test_handle_write_seed_returns_path(self, tmp_path: Path) -> None:
        """Result path should point to an existing seed file."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)

        result = await writer.handle_write_seed({"source": "test", "data": {"hello": "world"}})

        path = Path(result["path"])
        assert path.exists()
        content = path.read_text()
        assert "type: seed" in content
        assert "source: test" in content


class TestGardenWriterEvents:
    """Test EventBus emission from GardenWriter."""

    async def test_write_seed_emits_seed_written(self, tmp_path: Path) -> None:
        from bsage.core.events import EventBus, EventType

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault, event_bus=event_bus)
        await writer.write_seed("test-source", {"data": "hello"})

        events = [c.args[0] for c in sub.on_event.call_args_list]
        assert any(e.event_type == EventType.SEED_WRITTEN for e in events)

    async def test_write_garden_emits_garden_written(self, tmp_path: Path) -> None:
        from bsage.core.events import EventBus, EventType

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault, event_bus=event_bus)
        await writer.write_garden(
            {"title": "Test Note", "content": "body", "note_type": "idea", "source": "test"}
        )

        events = [c.args[0] for c in sub.on_event.call_args_list]
        assert any(e.event_type == EventType.GARDEN_WRITTEN for e in events)

    async def test_write_action_emits_action_logged(self, tmp_path: Path) -> None:
        from bsage.core.events import EventBus, EventType

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault, event_bus=event_bus)
        await writer.write_action("test-skill", "did something")

        events = [c.args[0] for c in sub.on_event.call_args_list]
        assert any(e.event_type == EventType.ACTION_LOGGED for e in events)

    async def test_no_events_when_event_bus_is_none(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)  # no event_bus
        path = await writer.write_seed("src", {"x": 1})
        assert path.exists()
