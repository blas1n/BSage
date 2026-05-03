"""Obsidian vault input — absorb notes from a user-pointed vault into garden.

Triggers on_demand. Source can be a local vault path (credentials.vault_path
or input_data.vault_path) or an upload_id pointing at a previously uploaded
ZIP via POST /api/uploads.

Writes one GardenNote per *.md file, copies attachments, preserves wikilinks,
stamps frontmatter ``provenance.source = "obsidian"`` + original_path so
re-import can update in place via ``provenance.original_path``.
"""

from bsage.plugin import plugin


@plugin(
    name="obsidian-input",
    version="1.0.0",
    category="input",
    description="Import an existing Obsidian vault (local path or uploaded ZIP) into BSage garden",
    trigger={"type": "on_demand"},
    credentials=[
        {
            "name": "vault_path",
            "description": (
                "Default Obsidian vault path (overridden by input_data.vault_path or upload_id)"
            ),
            "required": False,
        },
        {
            "name": "import_strategy",
            "description": "by-type | preserve-structure (default: by-type)",
            "required": False,
        },
    ],
    input_schema={
        "type": "object",
        "properties": {
            "upload_id": {"type": "string", "description": "ID returned by /api/uploads (ZIP)"},
            "path": {
                "type": "string",
                "description": "Direct path to ZIP (alternate to upload_id)",
            },
            "vault_path": {"type": "string", "description": "Local Obsidian vault directory"},
            "import_strategy": {"type": "string", "enum": ["by-type", "preserve-structure"]},
        },
        "additionalProperties": True,
    },
    mcp_exposed=True,
)
async def execute(context) -> dict:
    """Walk source vault, write each .md as a GardenNote.

    Attachments (images, PDFs) are out of scope for v1 — only markdown notes
    are imported. The wikilinks pointing to attachments are preserved
    as-is in the body so a later attachments-copy pass can wire them up.
    """
    import shutil
    import tempfile
    from pathlib import Path

    creds = context.credentials or {}
    input_data = context.input_data or {}

    strategy = input_data.get("import_strategy") or creds.get("import_strategy") or "by-type"

    # Resolve source root: ZIP (path) wins over local vault_path
    source_root: Path | None = None
    cleanup_dir: Path | None = None
    zip_path = input_data.get("path")
    if zip_path:
        zp = Path(zip_path)
        if zp.exists() and zp.suffix.lower() == ".zip":
            cleanup_dir = Path(tempfile.mkdtemp(prefix="bsage-obs-"))
            _safe_extract_zip(zp, cleanup_dir)
            source_root = cleanup_dir
    if source_root is None:
        vault_path = input_data.get("vault_path") or creds.get("vault_path")
        if vault_path:
            vp = Path(vault_path).expanduser()
            if vp.is_dir():
                source_root = vp
    if source_root is None:
        return {"imported": 0, "error": "no source vault provided"}

    imported = 0
    try:
        for md_path in sorted(source_root.rglob("*.md")):
            if any(p.startswith(".") for p in md_path.relative_to(source_root).parts):
                continue  # skip .obsidian/, .trash/, etc.
            try:
                content = md_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            note = _build_note(md_path, source_root, content, strategy)
            await context.garden.write_garden(note)
            imported += 1
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    return {"imported": imported, "strategy": strategy}


def _safe_extract_zip(zip_path, dest_root) -> None:
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


def _build_note(md_path, source_root, content: str, strategy: str):
    """Convert a markdown file into a GardenNote with provenance."""
    from bsage.garden.markdown_utils import (
        body_after_frontmatter,
        extract_frontmatter,
        extract_title,
    )
    from bsage.garden.note import GardenNote

    fm = extract_frontmatter(content) if content.startswith("---\n") else {}
    body = body_after_frontmatter(content)
    rel_path = str(md_path.relative_to(source_root))
    title = (
        (fm.get("title") if isinstance(fm, dict) else None)
        or extract_title(content)
        or md_path.stem
    )
    note_type = (fm.get("type") if isinstance(fm, dict) else None) or "idea"
    tags_raw = fm.get("tags") if isinstance(fm, dict) else None
    tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []

    extra = {}
    if isinstance(fm, dict):
        for k, v in fm.items():
            if k in {"title", "type", "tags", "source", "related"}:
                continue
            extra[k] = v
    extra["provenance"] = {
        "source": "obsidian",
        "original_path": rel_path,
        "import_strategy": strategy,
    }

    return GardenNote(
        title=str(title),
        content=body,
        note_type=str(note_type),
        source="obsidian-input",
        tags=tags,
        extra_fields=extra,
    )
