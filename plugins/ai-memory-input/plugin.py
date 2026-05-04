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


_VALID_NOTE_TYPES = frozenset(
    {"idea", "insight", "project", "event", "task", "fact", "person", "preference"}
)

# Map common AI-memory frontmatter `type:` values + filename prefixes onto
# BSage's GardenNote types. Falls through to `preference` for anything
# unrecognized (matches the original plugin's default).
_TYPE_ALIAS_MAP = {
    "feedback": "preference",
    "preference": "preference",
    "project": "project",
    "reference": "fact",
    "fact": "fact",
    "user": "person",
    "person": "person",
    "idea": "idea",
    "insight": "insight",
    "event": "event",
    "task": "task",
}


def _build_note(rel_path, content: str, source: str):
    """Build a GardenNote from a markdown file.

    Pulls title / type / tags from the frontmatter when present so each
    imported note carries useful metadata, not a fixed
    ``["ai-memory", source]`` tag set that's identical for every file.

    Title precedence:    frontmatter.name > frontmatter.title > first H1 > stem
    note_type precedence: frontmatter.type (mapped) > filename-prefix-mapped > preference
    Tags: union of base ["ai-memory", source] + filename-prefix tag (e.g.
    "feedback") + frontmatter.tags (deduped, lowercased).
    """
    import hashlib

    from bsage.garden.markdown_utils import extract_frontmatter
    from bsage.garden.note import GardenNote

    fm: dict | None = None
    if content.startswith("---\n"):
        try:
            parsed = extract_frontmatter(content)
            if isinstance(parsed, dict):
                fm = parsed
        except Exception:
            fm = None

    # Title
    title: str | None = None
    if fm:
        for k in ("name", "title"):
            v = fm.get(k)
            if isinstance(v, str) and v.strip():
                title = v.strip()
                break
    if title is None:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip() or None
                break
    if title is None:
        title = rel_path.stem

    # Filename-prefix tag — Claude Code convention names files
    # `feedback_xxx`, `project_xxx`, `reference_xxx`, `user_xxx`. Other
    # tools likely don't follow this; we still capture the first segment
    # if it matches a known type. Avoids leaking generic stems like
    # `MEMORY` as a tag.
    stem = rel_path.stem
    prefix = stem.split("_", 1)[0].lower() if "_" in stem else None
    prefix_tag = prefix if prefix in _TYPE_ALIAS_MAP else None

    # note_type — frontmatter.type wins, then prefix mapping, then default
    note_type = "preference"
    if fm:
        raw_type = fm.get("type")
        if isinstance(raw_type, str):
            mapped = _TYPE_ALIAS_MAP.get(raw_type.strip().lower())
            if mapped:
                note_type = mapped
    if note_type == "preference" and prefix_tag:
        mapped = _TYPE_ALIAS_MAP.get(prefix_tag)
        if mapped:
            note_type = mapped
    # final safety: must be in BSage's valid set
    if note_type not in _VALID_NOTE_TYPES:
        note_type = "preference"

    # Tags — union (preserve order, dedupe)
    tag_seq: list[str] = ["ai-memory", source]
    if prefix_tag:
        tag_seq.append(prefix_tag)
    if fm:
        fm_tags = fm.get("tags")
        if isinstance(fm_tags, list):
            for t in fm_tags:
                if isinstance(t, str) and t.strip():
                    tag_seq.append(t.strip().lower())
    seen: set[str] = set()
    tags: list[str] = []
    for t in tag_seq:
        if t not in seen:
            seen.add(t)
            tags.append(t)

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return GardenNote(
        title=title,
        content=content,
        note_type=note_type,
        source="ai-memory-input",
        tags=tags,
        confidence=0.9,
        extra_fields={
            "provenance": {
                "source": source,
                "filename": str(rel_path),
                "sha256": digest,
            },
        },
    )
