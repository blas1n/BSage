# BSage — Claude Code Instructions

## Project Overview

BSage is a personal AI agent that manages a 2nd Brain (Obsidian Vault). It collects data via InputSkills, processes it via ProcessSkills, and stores everything as Markdown in the Vault.

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
- `skill-system.md` — skill.yaml format, execute(context), is_dangerous
- `security.md` — No hardcoded secrets, SafeModeGuard, Vault boundary

## Project Structure

```
bsage/           # Main Python package
├── core/        # Config, SkillLoader, SkillRunner, AgentLoop, Scheduler, SafeMode
├── connectors/  # BaseConnector ABC, ConnectorManager
├── garden/      # GardenWriter, Vault
├── gateway/     # FastAPI Gateway (HTTP + WebSocket)
├── interface/   # ApprovalInterface implementations
└── tests/       # Unit tests (80%+ coverage required)
skills/          # Installed Skills (YAML + optional Python)
vault/           # Obsidian Vault — 2nd Brain (gitignored)
```

## Commit Format

```
type(scope): short description

- bullet points for details
```

No Co-Authored-By lines.
