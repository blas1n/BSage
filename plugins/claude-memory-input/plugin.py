"""claude.ai conversation export → seeds + IngestCompiler.

Accepts a claude.ai data export (ZIP from /api/uploads, or a directly
provided ZIP/JSON path). The export ZIP contains ``conversations.json``
keyed by ``uuid`` with a ``messages`` array.

Each conversation is written as a SEED (raw transcript + provenance);
:class:`IngestCompiler` then classifies it against the existing vault
and decides what to create / update / append. The plugin itself never
writes to ``garden/`` — that boundary is enforced by the restricted
garden interface plugins receive.
"""

from bsage.plugin import plugin


@plugin(
    name="claude-memory-input",
    version="2.0.0",
    category="input",
    description="Import claude.ai conversation export ZIP into BSage garden",
    trigger={"type": "on_demand"},
    credentials=[],
    input_schema={
        "type": "object",
        "properties": {
            "upload_id": {"type": "string", "description": "ID from POST /api/uploads"},
            "path": {"type": "string", "description": "Direct path to ZIP or conversations.json"},
        },
        "additionalProperties": True,
    },
    mcp_exposed=True,
)
async def execute(context) -> dict:
    """Parse claude.ai export at input_data.path → seeds + a single batched compile."""
    import json
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

    convs_path: Path | None = None
    cleanup_dir: Path | None = None

    try:
        if src.suffix.lower() == ".zip":
            cleanup_dir = Path(tempfile.mkdtemp(prefix="bsage-claude-"))
            _safe_extract(src, cleanup_dir)
            # Look for conversations.json anywhere in the extracted tree
            for candidate in cleanup_dir.rglob("conversations.json"):
                convs_path = candidate
                break
            if convs_path is None:
                return {"imported": 0, "error": "no conversations.json in zip"}
        else:
            convs_path = src

        try:
            raw = json.loads(convs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"imported": 0, "error": f"parse failed: {exc}"}

        if not isinstance(raw, list):
            return {"imported": 0, "error": "expected list of conversations"}

        seeds_written = 0
        batch_items: list[BatchItem] = []

        for conv in raw:
            if not isinstance(conv, dict):
                continue
            seed = _conversation_to_seed(conv)
            if seed is None:
                continue
            await context.garden.write_seed("claude-memory", seed)
            seeds_written += 1
            batch_items.append(
                BatchItem(
                    label=f"claude.ai/{seed['provenance']['external_id']}",
                    content=_compile_payload(seed),
                )
            )

        compile_result = None
        compile_error: str | None = None
        if context.ingest_compiler is not None and batch_items:
            try:
                compile_result = await context.ingest_compiler.compile_batch(
                    items=batch_items,
                    seed_source="claude-memory-input",
                )
            except Exception as exc:
                compile_error = str(exc)
                context.logger.warning(
                    "claude_memory_batch_compile_failed",
                    items=len(batch_items),
                    exc_info=True,
                )
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    return {
        "imported": seeds_written,
        "source": "claude.ai",
        "notes_created": compile_result.notes_created if compile_result else 0,
        "notes_updated": compile_result.notes_updated if compile_result else 0,
        "llm_calls": compile_result.llm_calls if compile_result else 0,
        "compile_error": compile_error,
        "compiler_available": context.ingest_compiler is not None,
    }


def _conversation_to_seed(conv: dict) -> dict | None:
    """Build a seed payload from a claude.ai conversation object.

    Carries the raw transcript and provenance — no pre-classification.
    The compiler decides note_type/tags/links against existing vault.
    """
    title = str(conv.get("name") or conv.get("title") or "Untitled chat")
    cid = str(conv.get("uuid") or conv.get("id") or title)
    created_at = conv.get("created_at")

    body_lines: list[str] = []
    messages = conv.get("messages") or conv.get("chat_messages") or []
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("sender") or msg.get("role") or "?"
            text = msg.get("text")
            if not isinstance(text, str):
                content = msg.get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
                else:
                    text = ""
            if text and text.strip():
                body_lines.append(f"**{role}**: {text}")

    body = "\n\n".join(body_lines) if body_lines else "(no text content)"

    return {
        "title": title,
        "content": body,
        "tags": ["claude", "memory"],
        "provenance": {
            "source": "claude.ai",
            "external_id": cid,
            "exported_at": created_at,
        },
    }


def _compile_payload(seed: dict) -> str:
    """Format a seed as the prompt-friendly payload for IngestCompiler."""
    return (
        f"# claude.ai conversation: {seed['title']}\n\n"
        f"external_id: {seed['provenance']['external_id']}\n\n"
        f"---\n\n"
        f"{seed['content']}"
    )


def _safe_extract(zip_path, dest_root) -> None:
    """Extract ZIP with zipslip protection."""
    import zipfile
    from pathlib import Path

    dest_root = Path(dest_root).resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            target = (dest_root / member).resolve()
            if not str(target).startswith(str(dest_root) + "/") and target != dest_root:
                raise ValueError(f"Refusing path traversal in zip: {member}")
        zf.extractall(dest_root)
