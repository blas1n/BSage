"""Git output Plugin — commits and pushes vault changes to a git repository."""

from bsage.plugin import plugin


@plugin(
    name="git-output",
    version="1.0.0",
    category="output",
    description="Auto-commit and push vault changes to a git repository",
    trigger={"type": "write_event"},
    credentials=[
        {
            "name": "repo_path",
            "description": "Path to git repository (default: vault path)",
            "required": False,
        },
        {"name": "remote", "description": "Git remote name (default: origin)", "required": False},
        {"name": "branch", "description": "Git branch (default: main)", "required": False},
        {
            "name": "auto_push",
            "description": "Auto-push after commit (default: true)",
            "required": False,
        },
    ],
)
async def execute(context) -> dict:
    """Stage, commit, and optionally push vault changes."""
    import asyncio
    import subprocess

    creds = context.credentials
    repo_path = creds.get("repo_path", "") or context.config.get("vault_path", "./vault")
    remote = creds.get("remote", "origin")
    branch = creds.get("branch", "main")
    auto_push = creds.get("auto_push", "true").lower() in ("true", "1", "yes")

    event_data = context.input_data or {}
    source = event_data.get("source", "unknown")
    event_type = event_data.get("event_type", "")

    async def _run_git(*args: str) -> subprocess.CompletedProcess:
        return await asyncio.to_thread(
            subprocess.run,
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=repo_path,
        )

    # Stage all changes
    await _run_git("add", "-A")

    # Check if there are changes to commit
    status = await _run_git("status", "--porcelain")
    if not status.stdout.strip():
        return {"committed": False, "reason": "nothing to commit"}

    # Commit
    message = f"BSage: {source} {event_type} update"
    commit_result = await _run_git("commit", "-m", message)
    if commit_result.returncode != 0:
        return {"committed": False, "error": commit_result.stderr.strip()}

    # Push
    pushed = False
    if auto_push:
        push_result = await _run_git("push", remote, branch)
        pushed = push_result.returncode == 0

    return {"committed": True, "pushed": pushed, "message": message}


@execute.setup
def setup(cred_store):
    """Configure git output with repository validation."""
    import asyncio
    import subprocess
    from pathlib import Path

    import click

    click.echo("Git Output Setup")
    repo_path = click.prompt("  Git repository path (default: vault path)", default="")
    remote = click.prompt("  Remote name", default="origin")
    branch = click.prompt("  Branch name", default="main")
    auto_push = click.prompt("  Auto-push after commit? (true/false)", default="true")

    if repo_path:
        p = Path(repo_path).expanduser().resolve()
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            cwd=str(p),
        )
        if result.returncode != 0:
            click.echo(f"Error: Not a git repository: {p}", err=True)
            raise SystemExit(1)
        click.echo(f"  Verified git repo: {p}")

    data = {"remote": remote, "branch": branch, "auto_push": auto_push}
    if repo_path:
        data["repo_path"] = repo_path
    asyncio.run(cred_store.store("git-output", data))
