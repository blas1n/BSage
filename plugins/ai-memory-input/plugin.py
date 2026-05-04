"""Generic AI memory uploader — accept .md files from any AI tool.

Replaces the old ``claude-code-memory-input`` plugin which only worked
self-hosted because it read ``~/.claude/CLAUDE.md`` from the BACKEND
filesystem (useless on a hosted deployment where the backend can't see
the user's laptop).

This plugin accepts:
- A single ``.md`` file via /api/uploads
- A ``.zip`` containing many ``.md`` files

Each file is written as a SEED (raw content + provenance) and then
handed to BSage's :class:`IngestCompiler`, which classifies the note
against existing vault content and decides what to create / update /
append. The plugin itself never writes to ``garden/`` — that boundary
is enforced by the restricted garden interface plugins receive.
"""

from bsage.plugin import plugin

# Source hints we accept. Anything else falls back to "custom".
_KNOWN_SOURCES = frozenset({"claude-code", "codex", "opencode", "cursor", "custom"})


@plugin(
    name="ai-memory-input",
    version="2.0.0",
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
    """Parse uploaded markdown(s) → seeds + a single batched compile call."""
    import shutil
    import tempfile
    from pathlib import Path

    from bsage.garden.ingest_compiler import BatchItem

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

        seeds_written = 0
        batch_items: list[BatchItem] = []

        for rel_path, content in md_files:
            seed_data = _build_seed_data(rel_path, content, source)
            await context.garden.write_seed(f"ai-memory/{source}", seed_data)
            seeds_written += 1
            batch_items.append(
                BatchItem(
                    label=f"{source}/{rel_path}",
                    content=_compile_payload(rel_path, content, source, seed_data),
                )
            )

        compile_result = None
        compile_error: str | None = None
        if context.ingest_compiler is not None and batch_items:
            try:
                compile_result = await context.ingest_compiler.compile_batch(
                    items=batch_items,
                    seed_source=f"ai-memory-input/{source}",
                )
            except Exception as exc:
                compile_error = str(exc)
                context.logger.warning(
                    "ai_memory_batch_compile_failed",
                    items=len(batch_items),
                    exc_info=True,
                )
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    return {
        "imported": seeds_written,
        "source": source,
        "notes_created": compile_result.notes_created if compile_result else 0,
        "notes_updated": compile_result.notes_updated if compile_result else 0,
        "llm_calls": compile_result.llm_calls if compile_result else 0,
        "compile_error": compile_error,
        "compiler_available": context.ingest_compiler is not None,
    }


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


def _build_seed_data(rel_path, content: str, source: str) -> dict:
    """Build seed payload — raw markdown plus provenance, no classification.

    Title is best-effort (frontmatter.name > frontmatter.title > first H1
    > filename stem) so seeds remain searchable, but we deliberately do
    NOT decide note_type or invent tags here — that's the compiler's
    job, against existing vault context.
    """
    import hashlib

    from bsage.garden.markdown_utils import extract_frontmatter

    fm: dict | None = None
    if content.startswith("---\n"):
        try:
            parsed = extract_frontmatter(content)
            if isinstance(parsed, dict):
                fm = parsed
        except Exception:
            fm = None

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

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return {
        "title": title,
        "content": content,
        "tags": ["ai-memory", source],
        "provenance": {
            "source": source,
            "filename": str(rel_path),
            "sha256": digest,
        },
    }


def _compile_payload(rel_path, content: str, source: str, seed_data: dict) -> str:
    """Build the prompt-friendly payload handed to IngestCompiler.

    The compiler sees the original markdown verbatim plus a small header
    that names the source file — enough context for the LLM to classify
    and to decide whether existing vault notes already cover this
    material.
    """
    return (
        f"# AI memory import (source: {source}, file: {rel_path})\n\n"
        f"Title hint: {seed_data['title']}\n\n"
        f"---\n\n"
        f"{content}"
    )
