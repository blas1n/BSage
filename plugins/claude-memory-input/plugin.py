"""claude.ai conversation export → BSage garden notes.

Accepts a claude.ai data export (ZIP from /api/uploads, or a directly
provided ZIP/JSON path). The export ZIP contains ``conversations.json``
keyed by ``uuid`` with a ``messages`` array. Each conversation becomes
one ``insight`` GardenNote.
"""

from bsage.plugin import plugin


@plugin(
    name="claude-memory-input",
    version="1.0.0",
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
    """Parse claude.ai export at input_data.path → write GardenNotes."""
    import json
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

        imported = 0
        if not isinstance(raw, list):
            return {"imported": 0, "error": "expected list of conversations"}

        for conv in raw:
            if not isinstance(conv, dict):
                continue
            note = _conversation_to_note(conv)
            if note is None:
                continue
            await context.garden.write_garden(note)
            imported += 1
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    return {"imported": imported, "source": "claude.ai"}


def _conversation_to_note(conv: dict):
    """Build a GardenNote from a claude.ai conversation object."""
    from bsage.garden.note import GardenNote

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

    return GardenNote(
        title=title,
        content=body,
        note_type="insight",
        source="claude-memory-input",
        tags=["claude", "memory"],
        confidence=0.7,
        extra_fields={
            "provenance": {
                "source": "claude.ai",
                "external_id": cid,
                "exported_at": created_at,
            },
        },
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
