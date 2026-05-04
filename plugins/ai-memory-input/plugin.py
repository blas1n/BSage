"""Generic AI memory uploader — accept .md files from any AI tool.

Replaces the old ``claude-code-memory-input`` plugin which only worked
self-hosted because it read ``~/.claude/CLAUDE.md`` from the BACKEND
filesystem (useless on a hosted deployment where the backend can't see
the user's laptop).

This plugin accepts:
- A single ``.md`` file via /api/uploads
- A ``.zip`` containing many ``.md`` files

Optional ``source`` hint (claude-code / codex / opencode / custom) tags
the resulting GardenNotes so users can filter by AI tool of origin.
"""

from bsage.plugin import plugin

# Source hints we accept. Anything else falls back to "custom".
_KNOWN_SOURCES = frozenset({"claude-code", "codex", "opencode", "cursor", "custom"})


@plugin(
    name="ai-memory-input",
    version="1.0.0",
    category="input",
    description=(
        "Import memory/context markdown files from any AI tool — Claude Code, "
        "Codex, opencode, etc. Drop in a .md file or a .zip of them."
    ),
    trigger={"type": "on_demand"},
    credentials=[],
    input_schema={
        "type": "object",
        "properties": {
            "upload_id": {"type": "string", "description": "ID from POST /api/uploads"},
            "path": {
                "type": "string",
                "description": "Direct file path (.md or .zip) — alternative to upload_id",
            },
            "source": {
                "type": "string",
                "enum": sorted(_KNOWN_SOURCES),
                "description": "AI tool that produced these files (default: custom)",
            },
        },
        "additionalProperties": True,
    },
    mcp_exposed=True,
)
async def execute(context) -> dict:
    """Parse uploaded markdown(s) → write each as a GardenNote."""
    import shutil
    import tempfile
    from pathlib import Path

    input_data = context.input_data or {}
    src_path = input_data.get("path")
    if not src_path:
        return {"imported": 0, "error": "no input file provided"}

    src = Path(src_path)
    if not src.exists():
        return {"imported": 0, "error": f"file not found: {src}"}

    raw_source = (input_data.get("source") or "").strip().lower()
    source = raw_source if raw_source in _KNOWN_SOURCES else "custom"

    md_files: list[tuple[Path, str]] = []  # (path-for-provenance, content)
    cleanup_dir: Path | None = None

    try:
        if src.suffix.lower() == ".zip":
            cleanup_dir = Path(tempfile.mkdtemp(prefix="bsage-ai-memory-"))
            _safe_extract(src, cleanup_dir)
            for md_path in sorted(cleanup_dir.rglob("*.md")):
                try:
                    md_files.append(
                        (md_path.relative_to(cleanup_dir), md_path.read_text(encoding="utf-8"))
                    )
                except (OSError, UnicodeDecodeError):
                    continue
        elif src.suffix.lower() == ".md":
            try:
                md_files.append((Path(src.name), src.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError) as exc:
                return {"imported": 0, "error": f"read failed: {exc}"}
        else:
            return {"imported": 0, "error": f"unsupported extension: {src.suffix}"}

        imported = 0
        for rel_path, content in md_files:
            note = _build_note(rel_path, content, source)
            await context.garden.write_garden(note)
            imported += 1
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    return {"imported": imported, "source": source}


def _safe_extract(zip_path, dest_root) -> None:
    """Extract ZIP with zipslip protection — refuse paths escaping dest_root."""
    import zipfile
    from pathlib import Path

    dest_root = Path(dest_root).resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            target = (dest_root / member).resolve()
            if not str(target).startswith(str(dest_root) + "/") and target != dest_root:
                raise ValueError(f"Refusing path traversal in zip: {member}")
        zf.extractall(dest_root)


def _build_note(rel_path, content: str, source: str):
    """Build a GardenNote from a markdown file.

    Title precedence: frontmatter.name > first H1 > filename stem.
    Many AI tools (Claude Code memory, Codex AGENTS.md) wrap notes in
    YAML frontmatter with a human-readable ``name:`` field — using that
    is far nicer than ``feedback_xxx_yyy_zzz`` filename fallback.
    """
    import hashlib

    from bsage.garden.markdown_utils import extract_frontmatter
    from bsage.garden.note import GardenNote

    title: str | None = None
    if content.startswith("---\n"):
        try:
            fm = extract_frontmatter(content)
            if isinstance(fm, dict):
                fm_name = fm.get("name") or fm.get("title")
                if isinstance(fm_name, str) and fm_name.strip():
                    title = fm_name.strip()
        except Exception:
            pass

    if title is None:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip() or None
                break

    if title is None:
        title = rel_path.stem

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return GardenNote(
        title=title,
        content=content,
        note_type="preference",
        source="ai-memory-input",
        tags=["ai-memory", source],
        confidence=0.9,
        extra_fields={
            "provenance": {
                "source": source,
                "filename": str(rel_path),
                "sha256": digest,
            },
        },
    )
