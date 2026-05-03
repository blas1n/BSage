"""Claude Code MEMORY.md → BSage garden notes.

Reads ~/.claude/CLAUDE.md (user-level) and any project-scoped
MEMORY.md / CLAUDE.md files under ~/.claude/projects/. Each file
becomes one ``preference`` GardenNote keyed by file_path + sha256
so subsequent runs are no-ops on unchanged files.
"""

from bsage.plugin import plugin


@plugin(
    name="claude-code-memory-input",
    version="1.0.0",
    category="input",
    description="Import Claude Code CLAUDE.md / MEMORY.md files into BSage garden",
    trigger={"type": "on_demand"},
    credentials=[
        {
            "name": "claude_root",
            "description": "Override ~/.claude location (default: $HOME/.claude)",
            "required": False,
        },
    ],
    input_schema={
        "type": "object",
        "properties": {
            "claude_root": {"type": "string"},
            "include_projects": {
                "type": "boolean",
                "description": "Walk ~/.claude/projects/*/CLAUDE.md too (default: true)",
            },
        },
        "additionalProperties": True,
    },
    mcp_exposed=True,
)
async def execute(context) -> dict:
    """Walk Claude Code memory files and write each as a GardenNote."""
    import hashlib
    import os
    from pathlib import Path

    from bsage.garden.note import GardenNote

    creds = context.credentials or {}
    input_data = context.input_data or {}

    root_str = (
        input_data.get("claude_root")
        or creds.get("claude_root")
        or os.environ.get("HOME", "") + "/.claude"
    )
    root = Path(root_str).expanduser()
    if not root.is_dir():
        return {"imported": 0, "error": f"Claude root not found: {root}"}

    include_projects = bool(input_data.get("include_projects", True))

    candidates: list[Path] = []
    user_md = root / "CLAUDE.md"
    if user_md.is_file():
        candidates.append(user_md)
    if include_projects:
        projects_dir = root / "projects"
        if projects_dir.is_dir():
            for p in projects_dir.rglob("CLAUDE.md"):
                candidates.append(p)
            for p in projects_dir.rglob("MEMORY.md"):
                candidates.append(p)
            # Also memory subdirs storing per-topic files
            for p in projects_dir.rglob("memory/*.md"):
                candidates.append(p)

    imported = 0
    for path in candidates:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0

        # Title — first H1 heading or filename stem
        title = path.stem
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip() or title
                break

        # Project slug for tagging
        try:
            rel = path.relative_to(root)
            project_slug = (
                rel.parts[1] if len(rel.parts) > 1 and rel.parts[0] == "projects" else "user"
            )
        except ValueError:
            project_slug = "user"

        note = GardenNote(
            title=title,
            content=content,
            note_type="preference",
            source="claude-code-memory-input",
            tags=["claude-code", project_slug],
            confidence=0.9,
            extra_fields={
                "provenance": {
                    "source": "claude-code",
                    "external_id": str(path),
                    "file_path": str(path),
                    "mtime": mtime,
                    "sha256": sha,
                },
            },
        )
        await context.garden.write_garden(note)
        imported += 1

    return {"imported": imported, "source": "claude-code"}
