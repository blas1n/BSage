"""ChatGPT export → seeds + IngestCompiler.

Accepts an OpenAI ``conversations.json`` export (uploaded via /api/uploads)
or, when present, a ``memory.json`` / ``user.json`` ``memories`` blob.

Each conversation / saved memory is written as a SEED with provenance
keyed by external_id; :class:`IngestCompiler` then classifies it
against existing vault content. The plugin itself never writes to
``garden/`` — that boundary is enforced by the restricted garden
interface plugins receive.
"""

from bsage.plugin import plugin


@plugin(
    name="chatgpt-memory-input",
    version="2.0.0",
    category="input",
    description="Import ChatGPT conversation + saved-memory exports into BSage garden",
    trigger={"type": "on_demand"},
    credentials=[],
    input_schema={
        "type": "object",
        "properties": {
            "upload_id": {"type": "string", "description": "ID from POST /api/uploads"},
            "path": {
                "type": "string",
                "description": "Direct file path (alternative to upload_id)",
            },
        },
        "additionalProperties": True,
    },
    mcp_exposed=True,
)
async def execute(context) -> dict:
    """Parse ChatGPT export at input_data.path → seeds + a single batched compile."""
    import json
    from pathlib import Path

    from bsage.garden.ingest_compiler import BatchItem

    input_data = context.input_data or {}
    src_path = input_data.get("path")
    if not src_path:
        return {"imported": 0, "error": "no input file provided"}

    src = Path(src_path)
    if not src.exists():
        return {"imported": 0, "error": f"file not found: {src}"}

    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"imported": 0, "error": f"parse failed: {exc}"}

    seeds: list[dict] = []

    # Path 1: conversations.json — list of conversation objects
    if isinstance(raw, list):
        for conv in raw:
            if not isinstance(conv, dict):
                continue
            seed = _conversation_to_seed(conv)
            if seed is not None:
                seeds.append(seed)

    # Path 2: memory.json or user.json with `memories` array
    elif isinstance(raw, dict):
        memories = raw.get("memories") or raw.get("memory")
        if isinstance(memories, list):
            for idx, mem in enumerate(memories):
                seed = _memory_to_seed(mem, idx)
                if seed is not None:
                    seeds.append(seed)

    seeds_written = 0
    batch_items: list[BatchItem] = []
    for seed in seeds:
        await context.garden.write_seed(f"chatgpt/{seed['kind']}", seed)
        seeds_written += 1
        batch_items.append(
            BatchItem(
                label=f"chatgpt/{seed['kind']}/{seed['provenance']['external_id']}",
                content=_compile_payload(seed),
            )
        )

    compile_result = None
    compile_error: str | None = None
    if context.ingest_compiler is not None and batch_items:
        try:
            compile_result = await context.ingest_compiler.compile_batch(
                items=batch_items,
                seed_source="chatgpt-memory-input",
            )
        except Exception as exc:
            compile_error = str(exc)
            context.logger.warning(
                "chatgpt_memory_batch_compile_failed",
                items=len(batch_items),
                exc_info=True,
            )

    return {
        "imported": seeds_written,
        "source": "chatgpt",
        "notes_created": compile_result.notes_created if compile_result else 0,
        "notes_updated": compile_result.notes_updated if compile_result else 0,
        "llm_calls": compile_result.llm_calls if compile_result else 0,
        "compile_error": compile_error,
        "compiler_available": context.ingest_compiler is not None,
    }


def _conversation_to_seed(conv: dict) -> dict | None:
    """Build a seed payload from a ChatGPT conversation object."""
    title = str(conv.get("title") or "Untitled chat")
    cid = str(conv.get("id") or conv.get("conversation_id") or title)
    create_time = conv.get("create_time")

    body_lines: list[str] = []
    mapping = conv.get("mapping")
    if isinstance(mapping, dict):
        msgs = []
        for node in mapping.values():
            if not isinstance(node, dict):
                continue
            m = node.get("message")
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            text = ""
            if isinstance(content, dict):
                parts = content.get("parts")
                if isinstance(parts, list):
                    text = "\n".join(str(p) for p in parts if isinstance(p, str))
            author = m.get("author") or {}
            role = author.get("role", "?") if isinstance(author, dict) else "?"
            ct = m.get("create_time") or 0
            if text.strip():
                msgs.append((ct or 0, role, text))
        msgs.sort()
        for _, role, text in msgs:
            body_lines.append(f"**{role}**: {text}")

    body = "\n\n".join(body_lines) if body_lines else "(no text content)"

    return {
        "kind": "conversation",
        "title": title,
        "content": body,
        "tags": ["chatgpt", "memory"],
        "provenance": {
            "source": "chatgpt",
            "external_id": cid,
            "exported_at": create_time,
        },
    }


def _memory_to_seed(mem, idx: int) -> dict | None:
    """Build a seed payload from a saved-memory entry (string or dict)."""
    if isinstance(mem, str):
        title = mem[:80]
        content = mem
        external_id = f"memory-{idx}"
    elif isinstance(mem, dict):
        content = str(mem.get("content") or mem.get("text") or "")
        title = mem.get("title") or content[:80] or f"Memory {idx + 1}"
        external_id = str(mem.get("id") or f"memory-{idx}")
    else:
        return None
    if not content.strip():
        return None

    return {
        "kind": "saved_memory",
        "title": str(title),
        "content": content,
        "tags": ["chatgpt", "memory", "saved"],
        "provenance": {
            "source": "chatgpt",
            "external_id": external_id,
            "kind": "saved_memory",
        },
    }


def _compile_payload(seed: dict) -> str:
    """Format a seed as the prompt-friendly payload for IngestCompiler."""
    return (
        f"# ChatGPT {seed['kind']}: {seed['title']}\n\n"
        f"external_id: {seed['provenance']['external_id']}\n\n"
        f"---\n\n"
        f"{seed['content']}"
    )
