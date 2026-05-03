"""Obsidian vault output — mirror BSage garden into a user-pointed vault.

Triggered on_demand (NOT write_event — user explicitly opted out of
continuous sync). Writes garden/ + seeds/ markdown files into the
configured ``output_vault_path``, preserving frontmatter and wikilinks.
Does not delete files at the destination.
"""

from bsage.plugin import plugin


@plugin(
    name="obsidian-output",
    version="1.0.0",
    category="output",
    description="Export BSage garden + seeds to a local Obsidian vault directory",
    trigger={"type": "on_demand"},
    credentials=[
        {
            "name": "output_vault_path",
            "description": "Destination vault directory (mirror target)",
            "required": True,
        },
    ],
    input_schema={
        "type": "object",
        "properties": {
            "output_vault_path": {
                "type": "string",
                "description": "Override credentials.output_vault_path for this run",
            },
            "overwrite": {
                "type": "boolean",
                "description": "If true, replace existing files at the destination (default: skip)",
            },
            "subdirs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Vault subdirs to mirror (default: garden, seeds)",
            },
        },
        "additionalProperties": True,
    },
    mcp_exposed=True,
)
async def execute(context) -> dict:
    """Read source notes from configured subdirs and mirror to output_vault_path."""
    from pathlib import Path

    creds = context.credentials or {}
    input_data = context.input_data or {}

    output_path_str = input_data.get("output_vault_path") or creds.get("output_vault_path")
    if not output_path_str:
        return {"written": 0, "skipped": 0, "error": "output_vault_path not configured"}

    output_root = Path(output_path_str).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)

    overwrite = bool(input_data.get("overwrite", False))
    subdirs = input_data.get("subdirs") or ["garden", "seeds"]

    written = 0
    skipped = 0

    for subdir in subdirs:
        try:
            note_paths = await context.garden.read_notes(subdir)
        except (FileNotFoundError, OSError):
            continue

        for src in note_paths:
            try:
                content = await context.garden.read_note_content(src)
            except (FileNotFoundError, OSError):
                continue
            # Preserve subdir-relative path under the output vault
            try:
                rel = src.relative_to(_vault_root_from(context))
            except (ValueError, AttributeError):
                rel = Path(subdir) / src.name
            dest = output_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and not overwrite:
                skipped += 1
                continue
            dest.write_text(content, encoding="utf-8")
            written += 1

    return {"written": written, "skipped": skipped, "destination": str(output_root)}


def _vault_root_from(context):
    """Resolve the vault root through the GardenWriter (private accessor)."""
    # Internal attribute — same access pattern the writer itself uses.
    vault = getattr(context.garden, "_vault", None)
    if vault is None:
        return None
    return getattr(vault, "root", None)
