"""GardenWriter — writes structured markdown notes to the vault.

Split out of the original monolithic ``bsage/garden/writer.py`` (M15,
Hardening Sprint 2). Responsibilities are now organised into three mixin
classes so each concern can be tested in isolation:

* :class:`_WriterIOMixin` — primitive seed / garden / action write operations
  (the "ingest" side of the writer).
* :class:`_WriterMutationMixin` — operations that modify or remove existing
  vault notes (update / append / delete / frontmatter status & maturity
  promotion).
* :class:`_WriterToolHandlersMixin` — adapters that turn LLM tool-call
  payloads into the underlying mutation/IO calls.

The public :class:`GardenWriter` is the composition of all three plus the
common constructor / sync-notification helpers. ``bsage.garden.writer``
re-exports it so existing imports keep working unchanged.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import yaml

from bsage.core.events import emit_event
from bsage.garden.note import (
    _MAX_ACTION_SUMMARY,
    _VALID_NOTE_TYPES,
    GardenNote,
    build_frontmatter,
    slugify,
)
from bsage.garden.vault import Vault

if TYPE_CHECKING:
    from bsage.core.events import EventBus
    from bsage.core.skill_context import GraphInterface
    from bsage.garden.audit_outbox import AiosqliteAuditOutbox
    from bsage.garden.ontology import OntologyRegistry
    from bsage.garden.sync import SyncManager

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------


class _WriterIOMixin:
    """Primitive ingest writes: seeds, garden notes, and append-only logs.

    Implementations rely on the attributes (``_vault``, ``_seed_lock``,
    ``_garden_lock``, ``_log_lock``, ``_event_bus``, ``_ontology``) initialised
    by :class:`GardenWriter`.
    """

    # --- attribute declarations for type checkers --------------------------
    _vault: Vault
    _sync_manager: SyncManager | None
    _event_bus: EventBus | None
    _ontology: OntologyRegistry | None
    _audit_outbox: AiosqliteAuditOutbox | None
    _default_tenant_id: str | None
    _log_lock: asyncio.Lock
    _garden_lock: asyncio.Lock
    _seed_lock: asyncio.Lock

    # --- helpers expected to be provided by GardenWriter -------------------
    async def _notify_sync(
        self, event_type_str: str, path: Path, source: str
    ) -> None:  # pragma: no cover - implemented in GardenWriter
        ...

    async def _emit_vault_modified(
        self,
        *,
        path: Path,
        operation: str,
        source: str,
        note_type: str | None = None,
        tenant_id: str | None = None,
    ) -> None:  # pragma: no cover - implemented in GardenWriter
        ...

    @staticmethod
    def _find_dedup_path(
        directory: Path, slug: str
    ) -> Path:  # pragma: no cover - implemented in GardenWriter
        ...

    def _resolve_folder(self, note_type: str) -> str:
        """Resolve the vault folder for a note type using ontology mapping."""
        if self._ontology:
            folder = self._ontology.get_entity_folder(note_type)
            if folder:
                return folder.rstrip("/")
        # Fallback: use type name as folder (e.g. "idea" → "ideas")
        return f"{note_type}s" if not note_type.endswith("s") else note_type

    def resolve_plugin_state_path(self, plugin_name: str, subpath: str = "_state.json") -> Path:
        """Resolve a plugin state file path within the vault.

        Plugins use this to safely store persistent state (e.g., polling cursors, offsets)
        without accessing private vault APIs.

        Args:
            plugin_name: Plugin name (e.g. "slack-input", "discord-input").
            subpath: Relative path within seeds/{plugin_name}/ (default: "_state.json").

        Returns:
            Resolved Path object pointing to seeds/{plugin_name}/{subpath}.

        Example:
            state_path = context.garden.resolve_plugin_state_path("slack-input")
            # → vault/seeds/slack-input/_state.json
        """
        return self._vault.resolve_path(f"seeds/{plugin_name}/{subpath}")

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

        source_dir = self._vault.resolve_path(f"seeds/{source}")
        source_dir.mkdir(parents=True, exist_ok=True)

        metadata: dict = {
            "type": "seed",
            "source": source,
            "captured_at": date_str,
        }
        if "title" in data:
            metadata["title"] = data["title"]
        if "tags" in data:
            metadata["tags"] = data["tags"]

        frontmatter = build_frontmatter(metadata)

        if "title" in data and "content" in data:
            body = data["content"]
        else:
            body = yaml.dump(data, default_flow_style=False, allow_unicode=True)
        content = f"{frontmatter}\n{body}\n"

        async with self._seed_lock:
            filename = now.strftime("%Y-%m-%d_%H%M%S") + ".md"
            file_path = source_dir / filename
            if file_path.exists():
                slug = now.strftime("%Y-%m-%d_%H%M%S")
                file_path = self._find_dedup_path(source_dir, slug)
            await asyncio.to_thread(file_path.write_text, content, encoding="utf-8")

        logger.info("seed_written", source=source, path=str(file_path))
        await self._notify_sync("seed", file_path, source)
        await emit_event(
            self._event_bus, "SEED_WRITTEN", {"path": str(file_path), "source": source}
        )
        await self._emit_vault_modified(
            path=file_path,
            operation="seed_written",
            source=source,
            note_type="seed",
        )
        return file_path

    async def write_garden(self, note: GardenNote | dict) -> Path:
        """Write a processed garden note with deduplication.

        v2.2: Uses the ontology folder mapping (e.g. ``ideas/``, ``events/``)
        instead of ``garden/{type}/``. Falls back to ``{note_type}/`` if no
        mapping exists.

        Args:
            note: The GardenNote or dict with note fields to write.

        Returns:
            Path to the created garden note file.
        """
        if isinstance(note, dict):
            note = GardenNote(**note)

        async with self._garden_lock:
            now = datetime.now(tz=UTC)
            date_str = now.strftime("%Y-%m-%d")
            slug = slugify(note.title)

            # v2.2: resolve folder from ontology or fall back to type name
            folder = self._resolve_folder(note.note_type)
            type_dir = self._vault.resolve_path(folder)
            type_dir.mkdir(parents=True, exist_ok=True)

            file_path = type_dir / f"{slug}.md"
            if file_path.exists():
                file_path = self._find_dedup_path(type_dir, slug)

            related_links = [f"[[{r}]]" for r in note.related]

            metadata: dict = {
                "type": note.note_type,
                "status": "seed",
                "source": note.source,
                "captured_at": date_str,
                "confidence": note.confidence,
                "knowledge_layer": note.knowledge_layer,
            }
            # Phase 0 P0.5 — tenant isolation: stamp tenant_id into frontmatter
            # so retrieval can filter by tenant. Falls back to writer default
            # when the caller didn't specify (cron, migration backfill).
            tenant_id = note.tenant_id or self._default_tenant_id
            if tenant_id:
                metadata["tenant_id"] = tenant_id
            if note.aliases:
                metadata["aliases"] = note.aliases
            # Extra fields for specialized note types (fact, preference, etc.)
            for key, value in note.extra_fields.items():
                metadata[key] = value
            # Typed relations — each key becomes a frontmatter key
            for rel_type, targets in note.relations.items():
                metadata[rel_type] = targets
            if related_links:
                metadata["related"] = related_links
            if note.tags:
                metadata["tags"] = note.tags

            frontmatter = build_frontmatter(metadata)
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
        await self._emit_vault_modified(
            path=file_path,
            operation="garden_written",
            source=note.source,
            note_type=note.note_type,
            tenant_id=tenant_id,
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

        async with self._log_lock:
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

        async with self._log_lock:
            await asyncio.to_thread(_write)
        logger.debug("input_log_written", source=source, path=str(log_path))

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


class _WriterMutationMixin:
    """Operations that modify, delete, or promote existing notes."""

    _vault: Vault
    _event_bus: EventBus | None
    _audit_outbox: AiosqliteAuditOutbox | None
    _default_tenant_id: str | None

    async def _notify_sync(
        self, event_type_str: str, path: Path, source: str
    ) -> None:  # pragma: no cover - implemented in GardenWriter
        ...

    async def _emit_vault_modified(
        self,
        *,
        path: Path,
        operation: str,
        source: str,
        note_type: str | None = None,
        tenant_id: str | None = None,
    ) -> None:  # pragma: no cover - implemented in GardenWriter
        ...

    # Re-exposed pre-compiled regex (kept on the class for backwards
    # compatibility with any external code that introspected ``_STATUS_RE``).
    _STATUS_RE = re.compile(r"^(status:\s*)\S+", re.MULTILINE)

    async def update_frontmatter_status(self, note_path: Path, new_status: str) -> None:
        """Update the ``status`` field in a note's YAML frontmatter in-place.

        Args:
            note_path: Absolute path to the markdown note.
            new_status: New maturity status value.
        """
        content = await asyncio.to_thread(note_path.read_text, "utf-8")
        updated = self._STATUS_RE.sub(rf"\g<1>{new_status}", content, count=1)
        if updated == content:
            return
        await asyncio.to_thread(note_path.write_text, updated, encoding="utf-8")
        rel_path = str(note_path.relative_to(self._vault.root))
        await emit_event(
            self._event_bus,
            "NOTE_UPDATED",
            {"path": rel_path, "field": "status", "new_value": new_status},
        )
        logger.info("maturity_status_updated", path=rel_path, new_status=new_status)

    async def promote_maturity(
        self,
        graph: GraphInterface | None,
        config: Any = None,
    ) -> dict[str, Any]:
        """Scan all garden notes and promote eligible ones.

        Args:
            graph: Graph interface for relationship/provenance queries.
            config: Optional ``MaturityConfig`` override; uses Settings defaults if None.

        Returns:
            Dict with ``promoted`` count, ``checked`` count, and ``details`` list.
        """
        from bsage.garden.markdown_utils import extract_frontmatter
        from bsage.garden.maturity import MaturityConfig, MaturityEvaluator

        if graph is None:
            return {"promoted": 0, "checked": 0, "details": []}

        if config is None:
            config = MaturityConfig()

        evaluator = MaturityEvaluator(graph, config)

        # v2.2: scan all entity-type folders, not just garden/
        scan_dirs = [
            "ideas",
            "insights",
            "projects",
            "people",
            "events",
            "tasks",
            "facts",
            "preferences",
        ]
        # Also scan legacy garden/ if it exists
        scan_dirs.append("garden")

        def _collect_md() -> list[Path]:
            files: list[Path] = []
            for d in scan_dirs:
                base = self._vault.root / d
                if base.is_dir():
                    files.extend(base.rglob("*.md"))
            return sorted(files)

        md_files = await asyncio.to_thread(_collect_md)
        promoted = 0
        details: list[dict[str, str]] = []

        for md_file in md_files:
            rel_path = str(md_file.relative_to(self._vault.root))
            content = await asyncio.to_thread(md_file.read_text, "utf-8")
            fm = extract_frontmatter(content)
            current_status = fm.get("status", "seed")

            new_status = await evaluator.evaluate(rel_path, current_status)
            if new_status is not None:
                await self.update_frontmatter_status(md_file, new_status.value)
                promoted += 1
                details.append(
                    {
                        "path": rel_path,
                        "from": current_status,
                        "to": new_status.value,
                    }
                )
                logger.info(
                    "note_promoted",
                    path=rel_path,
                    from_status=current_status,
                    to_status=new_status.value,
                )

        return {"promoted": promoted, "checked": len(md_files), "details": details}

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
        await self._emit_vault_modified(
            path=resolved,
            operation="note_updated",
            source="update",
        )
        return resolved

    async def update_frontmatter_related(self, note_path: str, linked_paths: set[str]) -> None:
        """Merge auto-discovered links into the note's frontmatter ``related`` field.

        Uses YAML parse/dump for clean frontmatter manipulation.
        Emits ``NOTE_UPDATED`` so output plugins can sync.

        Args:
            note_path: Vault-relative path to the note.
            linked_paths: Set of vault-relative paths to link to.
        """
        try:
            abs_path = self._vault.resolve_path(note_path)
            if not abs_path.resolve().is_relative_to(self._vault.root.resolve()):
                logger.warning("path_traversal_blocked", note_path=note_path)
                raise ValueError(f"Path traversal blocked: {note_path}")
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

        new_links = {f"[[{Path(lp).stem}]]" for lp in linked_paths}
        existing_related = metadata.get("related", [])
        existing_set = set(existing_related) if isinstance(existing_related, list) else set()
        merged = sorted(existing_set | new_links)
        if merged == sorted(existing_set):
            return

        metadata["related"] = merged
        new_fm = build_frontmatter(metadata)
        new_content = f"{new_fm}\n{body}"
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
        await self._emit_vault_modified(
            path=resolved,
            operation="note_appended",
            source="update",
        )

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
        await self._emit_vault_modified(
            path=resolved,
            operation="note_deleted",
            source="delete",
        )


class _WriterToolHandlersMixin:
    """LLM tool-call adapters — translate tool args to writer methods."""

    _vault: Vault

    async def write_garden(self, note: GardenNote | dict) -> Path:  # pragma: no cover - in IO mixin
        ...

    async def write_seed(self, source: str, data: dict) -> Path:  # pragma: no cover - in IO mixin
        ...

    async def update_note(
        self, path: str, content: str, *, preserve_frontmatter: bool = True
    ) -> Path:  # pragma: no cover - in mutation mixin
        ...

    async def append_to_note(
        self, path: str, text: str
    ) -> None:  # pragma: no cover - in mutation mixin
        ...

    async def delete_note(self, path: str) -> None:  # pragma: no cover - in mutation mixin
        ...

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


# ---------------------------------------------------------------------------
# Composed public class
# ---------------------------------------------------------------------------


class GardenWriter(_WriterIOMixin, _WriterMutationMixin, _WriterToolHandlersMixin):
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
        ontology: OntologyRegistry | None = None,
        default_tenant_id: str | None = None,
        audit_outbox: AiosqliteAuditOutbox | None = None,
    ) -> None:
        self._vault = vault
        self._sync_manager = sync_manager
        self._event_bus = event_bus
        self._ontology = ontology
        # Phase 0 P0.5 — fallback tenant id used when GardenNote.tenant_id is
        # None. Lets cron / migration writes still satisfy the tenant column
        # without dragging a principal through every internal call site.
        self._default_tenant_id = default_tenant_id
        # Phase Audit Batch 2 — optional outbox; when wired, the writer emits
        # ``sage.vault.file_modified`` events after every successful vault
        # write. ``None`` keeps test fixtures simple (no audit infra needed).
        self._audit_outbox = audit_outbox
        self._log_lock = asyncio.Lock()
        self._garden_lock = asyncio.Lock()
        self._seed_lock = asyncio.Lock()

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

    async def _emit_vault_modified(
        self,
        *,
        path: Path,
        operation: str,
        source: str,
        note_type: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Best-effort emit of ``sage.vault.file_modified`` after a write.

        For mutating ops on knowledge entries (update / append / delete) we
        also emit ``sage.knowledge.entry_updated`` so audit consumers can
        track lifecycle without parsing every vault path themselves.

        Failures here NEVER raise — audit observability must not break a
        successful vault write. The handler logs and continues.
        """
        if self._audit_outbox is None or not self._audit_outbox.is_open:
            return
        try:
            from bsvibe_audit import AuditActor, AuditResource
            from bsvibe_audit.events.sage import (
                KnowledgeEntryUpdated,
                VaultFileModified,
            )

            from bsage.garden.audit_outbox import safe_emit

            try:
                rel_path = str(path.relative_to(self._vault.root))
            except (ValueError, AttributeError):
                rel_path = str(path)

            actor = AuditActor(type="system", id="bsage")
            effective_tenant = tenant_id or self._default_tenant_id

            await safe_emit(
                self._audit_outbox,
                VaultFileModified(
                    actor=actor,
                    tenant_id=effective_tenant,
                    resource=AuditResource(type="vault_file", id=rel_path),
                    data={
                        "operation": operation,
                        "source": source,
                        "note_type": note_type,
                    },
                ),
            )

            # Knowledge-entry update lifecycle: only fire for in-place
            # mutations on garden notes (skip seed/action/input-log writes).
            mutation_ops = {"note_updated", "note_appended", "note_deleted"}
            non_knowledge_prefixes = ("seeds/", "actions/", ".bsage/")
            if operation in mutation_ops and not any(
                rel_path.startswith(p) for p in non_knowledge_prefixes
            ):
                note_id = Path(rel_path).stem
                await safe_emit(
                    self._audit_outbox,
                    KnowledgeEntryUpdated(
                        actor=actor,
                        tenant_id=effective_tenant,
                        resource=AuditResource(type="knowledge_entry", id=note_id),
                        data={
                            "operation": operation,
                            "source": source,
                            "path": rel_path,
                        },
                    ),
                )
        except Exception:  # noqa: BLE001 — audit must never break a write
            logger.warning("vault_audit_emit_failed", path=str(path), exc_info=True)

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
        max_attempts = 9999
        while counter <= max_attempts:
            candidate = directory / f"{slug}_{counter:03d}.md"
            if not candidate.exists():
                return candidate
            counter += 1
        # Fallback: use timestamp-based name to guarantee uniqueness
        ts = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S%f")
        return directory / f"{slug}_{ts}.md"


__all__ = ["GardenWriter"]
