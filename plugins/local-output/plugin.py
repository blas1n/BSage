"""Local output Plugin — syncs vault files to a local backup directory."""

from bsage.plugin import plugin


@plugin(
    name="local-output",
    version="1.0.0",
    category="output",
    description="Sync vault files to a local backup directory",
    trigger={"type": "write_event"},
    credentials=[
        {
            "name": "target_dir",
            "description": "Absolute path to backup directory",
            "required": True,
        },
    ],
)
async def execute(context) -> dict:
    """Copy the written vault file to the target directory."""
    import asyncio
    import shutil
    from pathlib import Path

    target_dir = Path(context.credentials.get("target_dir", ""))
    if not target_dir.is_absolute():
        return {"synced": False, "error": "target_dir must be an absolute path"}

    event_data = context.input_data or {}
    source_path = Path(event_data.get("path", ""))

    if not source_path.exists():
        return {"synced": False, "error": "source file does not exist"}

    # Preserve vault subdirectory structure (seeds/xxx, garden/xxx, actions/xxx)
    vault_path = Path(context.config.get("vault_path", "./vault")).resolve()
    try:
        relative = source_path.resolve().relative_to(vault_path)
    except ValueError:
        relative = Path(source_path.name)

    dest = target_dir / relative
    await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(shutil.copy2, str(source_path), str(dest))

    return {"synced": True, "path": str(dest)}


@execute.setup
def setup(cred_store):
    """Configure local backup directory with creation."""
    import asyncio
    from pathlib import Path

    import click

    click.echo("Local Output Setup")
    target_dir = click.prompt("  Absolute path to backup directory")

    p = Path(target_dir).expanduser()
    if not p.is_absolute():
        click.echo("Error: Path must be absolute.", err=True)
        raise SystemExit(1)
    if not p.is_dir() and click.confirm(f"  Directory does not exist: {p}. Create?", default=True):
        p.mkdir(parents=True, exist_ok=True)
        click.echo(f"  Created: {p}")

    asyncio.run(cred_store.store("local-output", {"target_dir": str(p)}))
