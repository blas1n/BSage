"""Garden Writer — formats collected data into Obsidian notes."""

import json
from typing import Any


async def execute(context: Any) -> dict[str, Any]:
    """Process input data and write structured notes to the garden."""
    input_data = context.input_data or {}
    source = input_data.get("source", "unknown")
    items = input_data.get("items", [])
    if isinstance(items, str):
        items = json.loads(items)

    notes_written = 0
    for item in items:
        title = item.get("title", "Untitled")
        content = item.get("content", "")
        tags = item.get("tags", [])

        await context.garden.write_garden(
            {
                "title": title,
                "content": content,
                "note_type": "idea",
                "source": source,
                "tags": tags,
            }
        )
        notes_written += 1

    context.logger.info("garden_writer_complete", notes_written=notes_written)
    return {"status": "ok", "notes_written": notes_written}
