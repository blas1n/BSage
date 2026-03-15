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
from bsage.core.patterns import RELATED_RE
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


UPDATE_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update-note",
        "description": (
            "Update the content of an existing vault note. "
            "Use when modifying, replacing, or adding links to an existing note."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Vault-relative path (e.g. garden/idea/my-note.md)",
                },
                "content": {
                    "type": "string",
                    "description": "New markdown body content",
                },
                "preserve_frontmatter": {
                    "type": "boolean",
                    "description": "Keep existing YAML frontmatter (default: true)",
                },
            },
            "required": ["path", "content"],
        },
    },
}

DELETE_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "delete-note",
        "description": (
            "Delete a note from the vault. Cannot delete action logs. "
            "Use when a note is outdated, duplicated, or no longer needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Vault-relative path to delete",
                },
            },
            "required": ["path"],
        },
    },
}

APPEND_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "append-note",
        "description": (
            "Append text to an existing vault note. "
            "Use when adding new content without replacing what already exists."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Vault-relative path (e.g. garden/idea/my-note.md)",
                },
                "text": {
                    "type": "string",
                    "description": "Text to append to the note",
                },
            },
            "required": ["path", "text"],
        },
    },
}

SEARCH_VAULT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search-vault",
        "description": (
            "Search the vault for relevant notes using semantic search. "
            "Use to find related notes, check for duplicates, or gather context."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "context_dirs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Vault subdirectories to search "
                        "(default: seeds, garden/idea, garden/insight)"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max notes to return (default: 10)",
                },
            },
            "required": ["query"],
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
        self._log_lock: asyncio.Lock | None = None

    def _get_log_lock(self) -> asyncio.Lock:
        if self._log_lock is None:
            self._log_lock = asyncio.Lock()
        return self._log_lock

    async def write_seed(self, source: str, data: dict) -> Path:
        """Write raw collected data as a seed note.

        Creates a file at seeds/{source}/{YYYY-MM-DD_HHMM}.md with
        YAML frontmatter containing type, source, and captured_at.

        When *data* contains ``title`` and/or ``tags``, they are promoted
        to frontmatter for fast RAG indexing. If ``title`` and ``content``
        are both present, the body is written as plain markdown instead of
        a YAML dump.

        Args:
            source: Name of the data source (e.g. "calendar", "idea").
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

        metadata: dict = {
            "type": "seed",
            "source": source,
            "captured_at": date_str,
        }
        if "title" in data:
            metadata["title"] = data["title"]
        if "tags" in data:
            metadata["tags"] = data["tags"]

        frontmatter = _build_frontmatter(metadata)

        if "title" in data and "content" in data:
            body = data["content"]
        else:
            body = yaml.dump(data, default_flow_style=False, allow_unicode=True)
        content = f"{frontmatter}\n{body}\n"

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

        async with self._get_log_lock():
            await asyncio.to_thread(_write)
        logger.info("action_logged", skill_name=skill_name, path=str(log_path))
        await self._notify_sync("action", log_path, skill_name)
        await emit_event(
            self._event_bus, "ACTION_LOGGED", {"path": str(log_path), "source": skill_name}
        )

    async def write_input_log(self, source: str, raw_text: str) -> None:
        """Write raw input data to the input-log directory for transparency.

        Creates or appends to actions/input-log/{YYYY-MM-DD}.md with a
        timestamped entry preserving the raw data before refinement.

        Args:
            source: Name of the input source (plugin name).
            raw_text: Raw input data as text.
        """
        now = datetime.now(tz=UTC)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        log_dir = self._vault.resolve_path("actions/input-log")
        await asyncio.to_thread(log_dir.mkdir, parents=True, exist_ok=True)

        log_path = log_dir / f"{date_str}.md"
        truncated = raw_text[:500] if len(raw_text) > 500 else raw_text
        entry = f"- **{time_str}** | `{source}` | {truncated}\n"

        def _write() -> None:
            if log_path.exists():
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(entry)
            else:
                log_path.write_text(f"# Input Log — {date_str}\n\n" + entry, encoding="utf-8")

        async with self._get_log_lock():
            await asyncio.to_thread(_write)
        logger.debug("input_log_written", source=source, path=str(log_path))

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

    async def update_note(
        self, path: str, content: str, *, preserve_frontmatter: bool = True
    ) -> Path:
        """Replace the content of an existing vault note.

        Args:
            path: Vault-relative path (e.g. ``"garden/idea/my-note.md"``).
            content: New markdown content.
            preserve_frontmatter: If True, keep existing YAML frontmatter
                and replace only the body.

        Returns:
            Resolved absolute path to the updated file.

        Raises:
            FileNotFoundError: If the note does not exist.
            ValueError: If the path escapes the vault boundary.
        """
        resolved = self._vault.resolve_path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"Note not found: {path}")

        if preserve_frontmatter:
            existing = await self._vault.read_note_content(resolved)
            if existing.startswith("---\n"):
                try:
                    end_idx = existing.index("\n---\n", 4)
                    frontmatter = existing[: end_idx + 5]
                    content = frontmatter + "\n" + content
                except ValueError:
                    pass

        await asyncio.to_thread(resolved.write_text, content, encoding="utf-8")
        logger.info("note_updated", path=str(resolved))
        await self._notify_sync("garden", resolved, "update")
        await emit_event(self._event_bus, "NOTE_UPDATED", {"path": str(resolved)})
        return resolved

    async def update_frontmatter_related(self, note_path: str, linked_paths: set[str]) -> None:
        """Merge auto-discovered links into the note's frontmatter ``related`` field.

        Converts vault-relative paths to ``[[wiki-link]]`` format and merges
        with any existing ``related`` entries using regex surgery on the raw
        frontmatter string (preserves key ordering and quoting style).
        Emits ``NOTE_UPDATED`` so output plugins can sync.

        Args:
            note_path: Vault-relative path to the note.
            linked_paths: Set of vault-relative paths to link to.
        """
        try:
            abs_path = self._vault.resolve_path(note_path)
            if not abs_path.resolve().is_relative_to(self._vault.root.resolve()):
                logger.warning("path_traversal_blocked", note_path=note_path)
                return
            if not abs_path.exists():
                return
            content = await self._vault.read_note_content(abs_path)
        except (FileNotFoundError, OSError, UnicodeDecodeError):
            return

        if not content.startswith("---\n"):
            return
        try:
            end_idx = content.index("\n---\n", 4)
        except ValueError:
            return

        fm_str = content[4:end_idx]
        body = content[end_idx + 5 :]

        try:
            metadata = yaml.safe_load(fm_str)
        except (yaml.YAMLError, ValueError):
            return
        if not isinstance(metadata, dict):
            return

        new_links: set[str] = {f"[[{Path(lp).stem}]]" for lp in linked_paths}
        existing_related = metadata.get("related", [])
        existing_set = set(existing_related) if isinstance(existing_related, list) else set()
        merged = sorted(existing_set | new_links)
        if merged == sorted(existing_related if isinstance(existing_related, list) else []):
            return

        related_lines = "related:\n" + "".join(f"- '{link}'\n" for link in merged)
        if RELATED_RE.search(fm_str):
            updated_fm = RELATED_RE.sub(related_lines, fm_str)
        else:
            sep = "" if fm_str.endswith("\n") else "\n"
            updated_fm = fm_str + sep + related_lines

        new_content = f"---\n{updated_fm}---\n{body}"
        await asyncio.to_thread(abs_path.write_text, new_content, encoding="utf-8")
        logger.debug("note_related_updated", note_path=note_path, links=len(merged))
        await self._notify_sync("garden", abs_path, "update")
        await emit_event(self._event_bus, "NOTE_UPDATED", {"path": note_path})

    async def append_to_note(self, path: str, text: str) -> None:
        """Append text to an existing vault note.

        Args:
            path: Vault-relative path.
            text: Text to append.

        Raises:
            FileNotFoundError: If the note does not exist.
            ValueError: If the path escapes the vault boundary.
        """
        resolved = self._vault.resolve_path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"Note not found: {path}")

        def _append() -> None:
            with resolved.open("a", encoding="utf-8") as f:
                f.write(text)

        await asyncio.to_thread(_append)
        logger.info("note_appended", path=str(resolved))
        await self._notify_sync("garden", resolved, "update")
        await emit_event(self._event_bus, "NOTE_UPDATED", {"path": str(resolved)})

    async def delete_note(self, path: str) -> None:
        """Delete a note from the vault.

        Args:
            path: Vault-relative path.

        Raises:
            ValueError: If path is in ``actions/`` (action logs are append-only)
                or escapes the vault boundary.
            FileNotFoundError: If the note does not exist.
        """
        if path.startswith("actions/"):
            raise ValueError("Cannot delete action logs")
        resolved = self._vault.resolve_path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"Note not found: {path}")

        await asyncio.to_thread(resolved.unlink)
        logger.info("note_deleted", path=str(resolved))
        await self._notify_sync("garden", resolved, "delete")
        await emit_event(self._event_bus, "NOTE_DELETED", {"path": str(resolved)})

    async def handle_update_note(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle an update-note tool call from the LLM.

        Args:
            args: Tool call arguments with path, content, and optional
                  preserve_frontmatter.

        Returns:
            Dict with status and path of the updated note.
        """
        path = args["path"]
        content = args["content"]
        preserve = args.get("preserve_frontmatter", True)
        resolved = await self.update_note(path, content, preserve_frontmatter=preserve)
        return {"status": "updated", "path": str(resolved)}

    async def handle_append_note(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle an append-note tool call from the LLM.

        Args:
            args: Tool call arguments with path and text.

        Returns:
            Dict with status and path of the appended note.
        """
        path = args["path"]
        text = args["text"]
        await self.append_to_note(path, text)
        resolved = self._vault.resolve_path(path)
        return {"status": "appended", "path": str(resolved)}

    async def handle_delete_note(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle a delete-note tool call from the LLM.

        Args:
            args: Tool call arguments with path.

        Returns:
            Dict with status and path of the deleted note.
        """
        path = args["path"]
        await self.delete_note(path)
        return {"status": "deleted", "path": path}

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
