"""ChatGPT export → BSage garden notes.

Accepts an OpenAI ``conversations.json`` export (uploaded via /api/uploads)
or, when present, a ``memory.json`` / ``user.json`` ``memories`` blob.
Each conversation becomes one ``insight`` GardenNote, each saved memory
becomes one ``preference`` GardenNote. Provenance.external_id keys
re-imports for in-place updates.
"""

from bsage.plugin import plugin


@plugin(
    name="chatgpt-memory-input",
    version="1.0.0",
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
    """Parse ChatGPT export at input_data.path → write GardenNotes."""
    import json
    from pathlib import Path

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

    imported = 0

    # Path 1: conversations.json — list of conversation objects
    if isinstance(raw, list):
        for conv in raw:
            if not isinstance(conv, dict):
                continue
            note = _conversation_to_note(conv)
            if note is None:
                continue
            await context.garden.write_garden(note)
            imported += 1

    # Path 2: memory.json or user.json with `memories` array
    elif isinstance(raw, dict):
        memories = raw.get("memories") or raw.get("memory")
        if isinstance(memories, list):
            for idx, mem in enumerate(memories):
                note = _memory_to_note(mem, idx)
                if note is None:
                    continue
                await context.garden.write_garden(note)
                imported += 1

    return {"imported": imported, "source": "chatgpt"}


def _conversation_to_note(conv: dict):
    """Build a GardenNote from a ChatGPT conversation object."""
    from bsage.garden.note import GardenNote

    title = str(conv.get("title") or "Untitled chat")
    cid = str(conv.get("id") or conv.get("conversation_id") or title)
    create_time = conv.get("create_time")

    # Extract user/assistant text from the message graph (`mapping`).
    body_lines: list[str] = []
    mapping = conv.get("mapping")
    if isinstance(mapping, dict):
        # Walk in roughly chronological order — sort by message create_time
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

    return GardenNote(
        title=title,
        content=body,
        note_type="insight",
        source="chatgpt-memory-input",
        tags=["chatgpt", "memory"],
        confidence=0.7,
        extra_fields={
            "provenance": {
                "source": "chatgpt",
                "external_id": cid,
                "exported_at": create_time,
            },
        },
    )


def _memory_to_note(mem, idx: int):
    """Build a GardenNote from a saved-memory entry (string or dict)."""
    from bsage.garden.note import GardenNote

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

    return GardenNote(
        title=str(title),
        content=content,
        note_type="preference",
        source="chatgpt-memory-input",
        tags=["chatgpt", "memory", "saved"],
        confidence=0.85,
        extra_fields={
            "provenance": {
                "source": "chatgpt",
                "external_id": external_id,
                "kind": "saved_memory",
            },
        },
    )
