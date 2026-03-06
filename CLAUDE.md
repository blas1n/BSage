# BSage — Claude Code Instructions

## Project Overview

BSage is a personal AI agent that manages a 2nd Brain (Obsidian Vault). It collects user data (active/passive) via input Plugins, provides tool functionality via process Plugins/Skills, and syncs the Vault to external storage via output Plugins. All data is stored as Markdown in the Vault.

## Key Commands

```bash
# Install dependencies
uv sync --all-extras

# Run tests with coverage
uv run pytest bsage/tests/ --cov=bsage --cov-fail-under=80 -v

# Lint and format check
uv run ruff check bsage/
uv run ruff format --check bsage/

# Start the Gateway server
uv run bsage run
```

## Architecture Rules

See `.claude/rules/` for detailed rules:
- `architecture.md` — Python 3.11+, uv, pydantic-settings, structlog, async, dataclasses
- `testing.md` — 80%+ coverage, mock external APIs, pytest-asyncio
- `skill-system.md` — Plugin (@plugin decorator) vs Skill (*.md frontmatter), DangerAnalyzer, trigger system
- `security.md` — No hardcoded secrets, SafeModeGuard, Vault boundary

## Project Structure

```
bsage/           # Main Python package
├── core/        # Config, PluginLoader, SkillLoader, AgentLoop, Scheduler, SafeMode, CredentialStore
├── garden/      # GardenWriter, Vault, SyncManager
├── gateway/     # FastAPI Gateway (HTTP + WebSocket)
├── interface/   # ApprovalInterface implementations
└── tests/       # Unit tests (80%+ coverage required)
plugins/         # Installed Plugins (Python, @plugin decorator)
skills/          # Installed Skills (Markdown, YAML frontmatter)
vault/           # Obsidian Vault — 2nd Brain (gitignored)
```

## Commit Format

```
type(scope): short description

- bullet points for details
```

No Co-Authored-By lines.
