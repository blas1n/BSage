"""GardenWriter — writes structured markdown notes to the vault."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import yaml

from bsage.core.events import emit_event
from bsage.garden.vault import Vault

if TYPE_CHECKING:
    from bsage.core.events import EventBus
    from bsage.garden.sync import SyncManager

logger = structlog.get_logger(__name__)


@dataclass
class GardenNote:
    """Structured representation of a garden note.

    Attributes:
        title: Human-readable title for the note.
        content: Markdown body content.
        note_type: Category of the note (seed / idea / project / insight).
        source: Name of the skill or source that created this note.
        related: List of related note titles for wiki-link references.
        tags: List of tags for categorization.
    """

    title: str
    content: str
    note_type: str  # seed / idea / project / insight
    source: str
    related: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def _slugify(title: str) -> str:
    """Convert a title to a URL-friendly slug.

    Lowercase, replace spaces with hyphens, remove special characters.
    Preserves Unicode word characters (Korean, Japanese, Chinese, etc.).
    Falls back to a timestamp when the result would be empty.
    """
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    if not slug:
        slug = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    return slug


def _build_frontmatter(metadata: dict) -> str:
    """Build YAML frontmatter block from a dict."""
    dumped = yaml.dump(metadata, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n"


_MAX_ACTION_SUMMARY = 200

_VALID_NOTE_TYPES = {"idea", "insight", "project"}

WRITE_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write-note",
        "description": (
            "Write a processed garden note — insights, analyzed conclusions, "
            "or structured summaries. Use when the content has been refined "
            "or the user asks for an insight/project note."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the note"},
                "content": {"type": "string", "description": "Markdown body content"},
                "note_type": {
                    "type": "string",
                    "enum": sorted(_VALID_NOTE_TYPES),
                    "description": "Note category (default: idea)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for categorization",
                },
            },
            "required": ["title", "content"],
        },
    },
}

WRITE_SEED_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write-seed",
        "description": (
            "Save a seed note — raw ideas, fleeting thoughts, or "
            "unprocessed data. Use by default when the user wants "
            "to save something new."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the seed",
                },
                "content": {
                    "type": "string",
                    "description": "Body text of the idea or data",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for categorization",
                },
            },
            "required": ["title", "content"],
        },
    },
}


class GardenWriter:
    """Writes seeds, garden notes, and action logs to the vault.

    Optionally notifies a SyncManager after each write so that
    registered backends (S3, Git, etc.) can sync the vault.

    Attributes:
        vault: The Vault instance for path resolution and file access.
    """

    def __init__(
        self,
        vault: Vault,
        sync_manager: SyncManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._vault = vault
        self._sync_manager = sync_manager
        self._event_bus = event_bus

    async def write_seed(self, source: str, data: dict) -> Path:
        """Write raw collected data as a seed note.

        Creates a file at seeds/{source}/{YYYY-MM-DD_HHMM}.md with
        YAML frontmatter containing type, source, and captured_at.

        Args:
            source: Name of the data source (e.g. "calendar", "google-calendar").
            data: Dictionary of collected data to serialize.

        Returns:
            Path to the created seed file.
        """
        now = datetime.now(tz=UTC)
        date_str = now.strftime("%Y-%m-%d")
        filename = now.strftime("%Y-%m-%d_%H%M") + ".md"

        source_dir = self._vault.resolve_path(f"seeds/{source}")
        source_dir.mkdir(parents=True, exist_ok=True)

        file_path = source_dir / filename

        frontmatter = _build_frontmatter(
            {
                "type": "seed",
                "source": source,
                "captured_at": date_str,
            }
        )

        body = yaml.dump(data, default_flow_style=False, allow_unicode=True)
        content = f"{frontmatter}\n{body}"

        await asyncio.to_thread(file_path.write_text, content, encoding="utf-8")
        logger.info("seed_written", source=source, path=str(file_path))
        await self._notify_sync("seed", file_path, source)
        await emit_event(
            self._event_bus, "SEED_WRITTEN", {"path": str(file_path), "source": source}
        )
        return file_path

    async def write_garden(self, note: GardenNote | dict) -> Path:
        """Write a processed garden note with deduplication.

        Creates a file at garden/{note_type}/{slug}.md. If a file with the
        same slug already exists, appends _001, _002, etc.

        Args:
            note: The GardenNote or dict with note fields to write.

        Returns:
            Path to the created garden note file.
        """
        if isinstance(note, dict):
            note = GardenNote(**note)
        now = datetime.now(tz=UTC)
        date_str = now.strftime("%Y-%m-%d")
        slug = _slugify(note.title)

        type_dir = self._vault.resolve_path(f"garden/{note.note_type}")
        type_dir.mkdir(parents=True, exist_ok=True)

        file_path = type_dir / f"{slug}.md"
        if file_path.exists():
            file_path = self._find_dedup_path(type_dir, slug)

        related_links = [f"[[{r}]]" for r in note.related]

        metadata: dict = {
            "type": note.note_type,
            "status": "growing",
            "source": note.source,
            "captured_at": date_str,
        }
        if related_links:
            metadata["related"] = related_links
        if note.tags:
            metadata["tags"] = note.tags

        frontmatter = _build_frontmatter(metadata)
        content = f"{frontmatter}\n# {note.title}\n\n{note.content}\n"

        await asyncio.to_thread(file_path.write_text, content, encoding="utf-8")
        logger.info(
            "garden_note_written",
            title=note.title,
            note_type=note.note_type,
            path=str(file_path),
        )
        await self._notify_sync("garden", file_path, note.source)
        await emit_event(
            self._event_bus, "GARDEN_WRITTEN", {"path": str(file_path), "source": note.source}
        )
        return file_path

    async def write_action(self, skill_name: str, summary: str) -> None:
        """Append an action log entry to the daily action log.

        Creates or appends to actions/{YYYY-MM-DD}.md with a timestamped
        entry including the skill name and summary.
        Summaries longer than _MAX_ACTION_SUMMARY characters are truncated.

        Args:
            skill_name: Name of the skill that performed the action.
            summary: Human-readable summary of the action.
        """
        now = datetime.now(tz=UTC)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        actions_dir = self._vault.resolve_path("actions")
        actions_dir.mkdir(parents=True, exist_ok=True)

        if len(summary) > _MAX_ACTION_SUMMARY:
            truncated = summary[:_MAX_ACTION_SUMMARY] + "…"
        else:
            truncated = summary
        log_path = actions_dir / f"{date_str}.md"
        entry = f"- **{time_str}** | `{skill_name}` | {truncated}\n"

        def _write() -> None:
            if log_path.exists():
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(entry)
            else:
                log_path.write_text(f"# Actions — {date_str}\n\n" + entry, encoding="utf-8")

        await asyncio.to_thread(_write)
        logger.info("action_logged", skill_name=skill_name, path=str(log_path))
        await self._notify_sync("action", log_path, skill_name)
        await emit_event(
            self._event_bus, "ACTION_LOGGED", {"path": str(log_path), "source": skill_name}
        )

    async def handle_write_note(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle a write-note tool call from the LLM.

        Validates args, writes a garden note, and returns a result dict.

        Args:
            args: Tool call arguments with title, content, and optional
                  note_type and tags.

        Returns:
            Dict with status, title, note_type, and path of the created note.
        """
        title = args.get("title", "Untitled")
        content = args.get("content", "")
        note_type = args.get("note_type", "idea")
        tags = args.get("tags", [])

        if note_type not in _VALID_NOTE_TYPES:
            note_type = "idea"

        path = await self.write_garden(
            {
                "title": title,
                "content": content,
                "note_type": note_type,
                "source": "chat",
                "tags": tags,
            }
        )
        return {"status": "saved", "title": title, "note_type": note_type, "path": str(path)}

    async def handle_write_seed(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle a write-seed tool call from the LLM.

        Writes a structured seed with title/content. Source is always
        ``"idea"`` to separate user ideas from automatic data captures.

        Args:
            args: Tool call arguments with title, content, and optional tags.

        Returns:
            Dict with status, title, and path of the created seed.
        """
        title = args.get("title", "Untitled")
        content = args.get("content", "")
        tags = args.get("tags", [])
        data: dict[str, Any] = {"title": title, "content": content}
        if tags:
            data["tags"] = tags
        path = await self.write_seed("idea", data)
        return {"status": "saved", "title": title, "path": str(path)}

    async def read_notes(self, subdir: str) -> list[Path]:
        """Read notes from a vault subdirectory.

        Delegates to the vault's read_notes method.

        Args:
            subdir: Relative directory path within the vault.

        Returns:
            Sorted list of .md file paths.
        """
        return await self._vault.read_notes(subdir)

    async def read_note_content(self, path: Path) -> str:
        """Read the text content of a note file asynchronously.

        Delegates to the vault's read_note_content method.

        Args:
            path: Absolute path to the note file.

        Returns:
            The text content of the note.
        """
        return await self._vault.read_note_content(path)

    async def _notify_sync(self, event_type_str: str, path: Path, source: str) -> None:
        """Notify sync manager of a write event, if configured."""
        if self._sync_manager is None:
            return
        from bsage.garden.sync import WriteEvent, WriteEventType

        event = WriteEvent(
            event_type=WriteEventType(event_type_str),
            path=path,
            source=source,
        )
        await self._sync_manager.notify(event)

    @staticmethod
    def _find_dedup_path(directory: Path, slug: str) -> Path:
        """Find the next available deduplicated filename.

        Searches for slug_001.md, slug_002.md, etc. until a free name is found.

        Args:
            directory: The directory to check.
            slug: The base slug for the filename.

        Returns:
            Path with a unique deduplicated filename.
        """
        counter = 1
        while True:
            candidate = directory / f"{slug}_{counter:03d}.md"
            if not candidate.exists():
                return candidate
            counter += 1
