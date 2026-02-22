"""GardenWriter — writes structured markdown notes to the vault."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import structlog
import yaml

from bsage.garden.vault import Vault

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
    """
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug


def _build_frontmatter(metadata: dict) -> str:
    """Build YAML frontmatter block from a dict."""
    dumped = yaml.dump(metadata, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n"


class GardenWriter:
    """Writes seeds, garden notes, and action logs to the vault.

    Attributes:
        vault: The Vault instance for path resolution and file access.
    """

    def __init__(self, vault: Vault) -> None:
        self._vault = vault

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

        file_path.write_text(content, encoding="utf-8")
        logger.info("seed_written", source=source, path=str(file_path))
        return file_path

    async def write_garden(self, note: GardenNote) -> Path:
        """Write a processed garden note with deduplication.

        Creates a file at garden/{note_type}/{slug}.md. If a file with the
        same slug already exists, appends _001, _002, etc.

        Args:
            note: The GardenNote to write.

        Returns:
            Path to the created garden note file.
        """
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

        file_path.write_text(content, encoding="utf-8")
        logger.info(
            "garden_note_written",
            title=note.title,
            note_type=note.note_type,
            path=str(file_path),
        )
        return file_path

    async def write_action(self, skill_name: str, summary: str) -> None:
        """Append an action log entry to the daily action log.

        Creates or appends to actions/{YYYY-MM-DD}.md with a timestamped
        entry including the skill name and summary.

        Args:
            skill_name: Name of the skill that performed the action.
            summary: Human-readable summary of the action.
        """
        now = datetime.now(tz=UTC)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        actions_dir = self._vault.resolve_path("actions")
        actions_dir.mkdir(parents=True, exist_ok=True)

        log_path = actions_dir / f"{date_str}.md"
        entry = f"- **{time_str}** | `{skill_name}` | {summary}\n"

        if log_path.exists():
            with log_path.open("a", encoding="utf-8") as f:
                f.write(entry)
        else:
            header = f"# Actions — {date_str}\n\n"
            log_path.write_text(header + entry, encoding="utf-8")

        logger.info("action_logged", skill_name=skill_name, path=str(log_path))

    async def read_notes(self, subdir: str) -> list[Path]:
        """Read notes from a vault subdirectory.

        Delegates to the vault's read_notes method.

        Args:
            subdir: Relative directory path within the vault.

        Returns:
            Sorted list of .md file paths.
        """
        return self._vault.read_notes(subdir)

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
