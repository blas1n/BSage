"""iCloud output Plugin — syncs vault files to iCloud Drive via local mount."""

from bsage.plugin import plugin


@plugin(
    name="icloud-output",
    version="1.0.0",
    category="output",
    description="Sync vault files to iCloud Drive (via local mount point)",
    trigger={"type": "write_event"},
    credentials=[
        {
            "name": "icloud_path",
            "description": (
                "Local iCloud Drive mount path"
                " (e.g. ~/Library/Mobile Documents/com~apple~CloudDocs/BSage)"
            ),
            "required": True,
        },
    ],
)
async def execute(context) -> dict:
    """Copy the written vault file to the iCloud Drive directory."""
    import asyncio
    import shutil
    from pathlib import Path

    icloud_path = Path(context.credentials.get("icloud_path", "")).expanduser()

    if not icloud_path.is_dir():
        return {"synced": False, "error": f"iCloud path does not exist: {icloud_path}"}

    event_data = context.input_data or {}
    source_path = Path(event_data.get("path", ""))

    if not source_path.exists():
        return {"synced": False, "error": "source file does not exist"}

    # Preserve vault structure
    vault_path = Path(context.config.get("vault_path", "./vault")).resolve()
    try:
        relative = source_path.resolve().relative_to(vault_path)
    except ValueError:
        relative = Path(source_path.name)

    dest = icloud_path / relative
    await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(shutil.copy2, str(source_path), str(dest))

    return {"synced": True, "path": str(dest)}


@execute.setup
def setup(cred_store):
    """Configure iCloud Drive path with directory validation."""
    import asyncio
    from pathlib import Path

    import click

    click.echo("iCloud Output Setup")
    icloud_path = click.prompt(
        "  iCloud Drive mount path (e.g. ~/Library/Mobile Documents/com~apple~CloudDocs/BSage)"
    )

    p = Path(icloud_path).expanduser()
    if not p.is_dir() and click.confirm(f"  Directory does not exist: {p}. Create?", default=True):
        p.mkdir(parents=True, exist_ok=True)
        click.echo(f"  Created: {p}")

    asyncio.run(cred_store.store("icloud-output", {"icloud_path": str(p)}))
