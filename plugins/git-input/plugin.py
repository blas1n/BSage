"""Git commit/diff input Plugin — collects recent commits from a local repository."""

from bsage.plugin import plugin


@plugin(
    name="git-input",
    version="1.0.0",
    category="input",
    description="Collect git commit messages, diffs, and branch info from local repositories",
    trigger={"type": "cron", "schedule": "0 */6 * * *"},
    credentials=[
        {"name": "repo_path", "description": "Path to the git repository", "required": True},
        {"name": "since_days", "description": "Days to look back (default: 7)", "required": False},
    ],
)
async def execute(context) -> dict:
    """Collect recent git commits and store as seeds."""
    import asyncio
    import subprocess

    repo_path = context.credentials.get("repo_path", ".")
    since_days = int(context.credentials.get("since_days", 7))

    result = await asyncio.to_thread(
        subprocess.run,
        [
            "git",
            "log",
            f"--since={since_days} days ago",
            "--pretty=format:%H|%an|%s|%ai",
            "--no-merges",
        ],
        capture_output=True,
        text=True,
        cwd=repo_path,
    )

    commits = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        hash_, author, message, date = parts
        diff_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "diff", "--stat", f"{hash_}~1", hash_],
            capture_output=True,
            text=True,
            cwd=repo_path,
        )
        commits.append(
            {
                "hash": hash_,
                "author": author,
                "message": message,
                "date": date,
                "diff_stat": diff_result.stdout.strip(),
            }
        )

    await context.garden.write_seed("git", {"commits": commits, "repo_path": repo_path})
    return {"collected": len(commits)}


@execute.setup
def setup(cred_store):
    """Configure git repository path with validation."""
    import asyncio
    import subprocess
    from pathlib import Path

    import click

    click.echo("Git Input Setup")
    repo_path = click.prompt("  Path to git repository")
    since_days = click.prompt("  Days to look back", default="7")

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

    data = {"repo_path": str(p), "since_days": since_days}
    asyncio.run(cred_store.store("git-input", data))
