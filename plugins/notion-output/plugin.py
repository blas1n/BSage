"""Notion output Plugin — syncs vault notes to Notion as pages."""

from bsage.plugin import plugin


@plugin(
    name="notion-output",
    version="1.0.0",
    category="output",
    description="Sync vault notes to Notion pages in a database",
    trigger={"type": "write_event"},
    credentials=[
        {"name": "notion_api_key", "description": "Notion integration API key", "required": True},
        {
            "name": "database_id",
            "description": "Notion database ID to write pages to",
            "required": True,
        },
    ],
)
async def execute(context) -> dict:
    """Create or update a Notion page from a vault note."""
    from pathlib import Path

    import httpx

    creds = context.credentials
    api_key = creds.get("notion_api_key", "")
    database_id = creds.get("database_id", "")

    event_data = context.input_data or {}
    source_path = Path(event_data.get("path", ""))

    if not source_path.exists() or source_path.suffix != ".md":
        return {"synced": False, "error": "source file does not exist or is not markdown"}

    content = source_path.read_text("utf-8")

    # Parse frontmatter and body
    title = source_path.stem
    body = content
    metadata: dict = {}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import contextlib

            import yaml

            with contextlib.suppress(yaml.YAMLError):
                metadata = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
            title = metadata.get("title", title)

    # Convert markdown body to Notion blocks (simplified: paragraph blocks)
    blocks = _markdown_to_blocks(body)

    # Build Notion page payload
    payload = {
        "parent": {"database_id": database_id},
        "properties": {
            "Name": {"title": [{"text": {"content": title}}]},
        },
        "children": blocks,
    }

    # Add tags if present
    tags = metadata.get("tags", [])
    if tags:
        payload["properties"]["Tags"] = {
            "multi_select": [{"name": t} for t in tags],
        }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.notion.com/v1/pages",
            json=payload,
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()

    page_id = result.get("id", "")
    return {"synced": True, "page_id": page_id, "title": title}


def _markdown_to_blocks(md: str) -> list[dict]:
    """Convert markdown text to Notion block objects (simplified)."""
    blocks: list[dict] = []
    for line in md.split("\n"):
        if not line.strip():
            continue
        if line.startswith("# "):
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {"rich_text": [{"text": {"content": line[2:].strip()}}]},
                }
            )
        elif line.startswith("## "):
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": [{"text": {"content": line[3:].strip()}}]},
                }
            )
        elif line.startswith("### "):
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": [{"text": {"content": line[4:].strip()}}]},
                }
            )
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"text": {"content": line[2:].strip()}}],
                    },
                }
            )
        else:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"text": {"content": line.strip()}}]},
                }
            )
    return blocks


@execute.setup
async def setup(cred_store):
    """Configure Notion API credentials with database access check."""
    import click
    import httpx

    click.echo("Notion Output Setup")
    api_key = click.prompt("  Notion integration API key")
    database_id = click.prompt("  Notion database ID")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.notion.com/v1/databases/{database_id}",
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code != 200:
            click.echo(f"Error: Notion API returned HTTP {resp.status_code}", err=True)
            raise SystemExit(1)
        db_title = resp.json().get("title", [{}])
        name = db_title[0].get("plain_text", database_id) if db_title else database_id
        click.echo(f"  Verified database: {name}")

    data = {"notion_api_key": api_key, "database_id": database_id}
    await cred_store.store("notion-output", data)
