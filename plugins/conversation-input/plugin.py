"""Conversation history input Plugin — collects AI chat history from local files."""

from bsage.plugin import plugin


@plugin(
    name="conversation-input",
    version="1.0.0",
    category="input",
    description="Collect AI conversation history from local files and store as seeds",
    trigger={"type": "cron", "schedule": "0 8 * * *"},
    credentials=[
        {
            "name": "history_path",
            "description": "Path to conversation history directory",
            "required": True,
        },
        {
            "name": "format",
            "description": "File format: jsonl, json, or markdown (default: jsonl)",
            "required": False,
        },
    ],
)
async def execute(context) -> dict:
    """Read conversation files and write to seeds."""
    import asyncio
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    history_path = Path(context.credentials.get("history_path", "."))
    fmt = context.credentials.get("format", "jsonl")
    marker_file = history_path / ".last_read"

    last_read = None
    if marker_file.exists():
        last_read = datetime.fromisoformat(marker_file.read_text().strip())

    def _scan_files() -> list[Path]:
        if not history_path.is_dir():
            return []
        extensions = {"jsonl": ".jsonl", "json": ".json", "markdown": ".md"}
        ext = extensions.get(fmt, ".jsonl")
        files = sorted(history_path.glob(f"*{ext}"), key=lambda p: p.stat().st_mtime)
        if last_read:
            files = [
                f for f in files if datetime.fromtimestamp(f.stat().st_mtime, tz=UTC) > last_read
            ]
        return files

    files = await asyncio.to_thread(_scan_files)
    all_messages: list[dict] = []

    for file_path in files:
        content = await asyncio.to_thread(file_path.read_text, "utf-8")
        if fmt == "jsonl":
            for line in content.splitlines():
                line = line.strip()
                if line:
                    try:
                        all_messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        elif fmt == "json":
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    all_messages.extend(data)
                else:
                    all_messages.append(data)
            except json.JSONDecodeError:
                continue
        elif fmt == "markdown":
            all_messages.append({"file": file_path.name, "content": content})

    if all_messages:
        await context.garden.write_seed("conversations", {"messages": all_messages})

    # Update marker
    now = datetime.now(tz=UTC).isoformat()
    await asyncio.to_thread(marker_file.write_text, now)

    return {"collected": len(all_messages)}


@execute.setup
def setup(cred_store):
    """Configure conversation history path with directory validation."""
    import asyncio
    from pathlib import Path

    import click

    click.echo("Conversation Input Setup")
    history_path = click.prompt("  Path to conversation history directory")
    fmt = click.prompt("  File format (jsonl/json/markdown)", default="jsonl")

    p = Path(history_path).expanduser()
    if not p.is_dir():
        click.echo(f"Warning: Directory does not exist yet: {p}")
        if click.confirm("  Create it?", default=True):
            p.mkdir(parents=True, exist_ok=True)
            click.echo(f"  Created: {p}")

    data = {"history_path": str(p), "format": fmt}
    asyncio.run(cred_store.store("conversation-input", data))
