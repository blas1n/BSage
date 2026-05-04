"""Obsidian vault input — absorb notes from a user-pointed vault.

Triggers on_demand. Source can be a local vault path (credentials.vault_path
or input_data.vault_path) or an upload_id pointing at a previously uploaded
ZIP via POST /api/uploads.

Each .md file is written as a SEED with provenance keyed by
``original_path``; :class:`IngestCompiler` then classifies it against
existing vault content and decides what to create / update / append.
The plugin itself never writes to ``garden/`` — that boundary is
enforced by the restricted garden interface plugins receive.
"""

from bsage.plugin import plugin


@plugin(
    name="obsidian-input",
    version="2.0.0",
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
    """Walk source vault, seed each .md file, then run a single batched compile.

    Attachments (images, PDFs) are out of scope — only markdown is
    seeded. Wikilinks are preserved verbatim in the body so the
    compiler can reason about them when classifying.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from bsage.garden.ingest_compiler import BatchItem

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

    seeds_written = 0
    batch_items: list[BatchItem] = []

    try:
        for md_path in sorted(source_root.rglob("*.md")):
            if any(p.startswith(".") for p in md_path.relative_to(source_root).parts):
                continue  # skip .obsidian/, .trash/, etc.
            try:
                content = md_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            seed = _build_seed_data(md_path, source_root, content, strategy)
            await context.garden.write_seed("obsidian", seed)
            seeds_written += 1
            batch_items.append(
                BatchItem(
                    label=f"obsidian/{seed['provenance']['original_path']}",
                    content=_compile_payload(seed),
                )
            )

        compile_result = None
        compile_error: str | None = None
        if context.ingest_compiler is not None and batch_items:
            try:
                compile_result = await context.ingest_compiler.compile_batch(
                    items=batch_items,
                    seed_source="obsidian-input",
                )
            except Exception as exc:
                compile_error = str(exc)
                context.logger.warning(
                    "obsidian_batch_compile_failed",
                    items=len(batch_items),
                    exc_info=True,
                )
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    return {
        "imported": seeds_written,
        "strategy": strategy,
        "notes_created": compile_result.notes_created if compile_result else 0,
        "notes_updated": compile_result.notes_updated if compile_result else 0,
        "llm_calls": compile_result.llm_calls if compile_result else 0,
        "compile_error": compile_error,
        "compiler_available": context.ingest_compiler is not None,
    }


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


def _build_seed_data(md_path, source_root, content: str, strategy: str) -> dict:
    """Build seed payload — raw markdown plus provenance.

    Title is best-effort (frontmatter > first H1 > filename) so the
    seed is searchable, but we deliberately don't decide note_type or
    invent tags — the compiler classifies against existing vault.
    """
    from bsage.garden.markdown_utils import extract_frontmatter, extract_title

    fm = extract_frontmatter(content) if content.startswith("---\n") else {}
    rel_path = str(md_path.relative_to(source_root))
    title = (
        (fm.get("title") if isinstance(fm, dict) else None)
        or extract_title(content)
        or md_path.stem
    )
    tags_raw = fm.get("tags") if isinstance(fm, dict) else None
    tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []

    return {
        "title": str(title),
        "content": content,
        "tags": [*tags, "obsidian"],
        "provenance": {
            "source": "obsidian",
            "original_path": rel_path,
            "import_strategy": strategy,
        },
    }


def _compile_payload(seed: dict) -> str:
    """Format a seed as the prompt-friendly payload for IngestCompiler."""
    return (
        f"# Obsidian note: {seed['title']}\n\n"
        f"original_path: {seed['provenance']['original_path']}\n\n"
        f"---\n\n"
        f"{seed['content']}"
    )
