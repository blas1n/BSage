# BSage

> *My BSage knows me better than I do.*

Personal AI agent that records everything about you in a 2nd Brain (Obsidian Vault) and proactively acts on it. A transparent, safe alternative to OpenClaw.

## Architecture

```
┌─────────────────────────────────────────────────┐
│              INTERFACE LAYER                     │
│   CLI  │  GUI chatbot  │  Telegram  │  WhatsApp │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│            GATEWAY (FastAPI)                     │
│   HTTP REST  │  WebSocket  │  SafeMode Approval │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│                CORE ENGINE                       │
│  Scheduler → AgentLoop → SafeModeGuard          │
│  SkillLoader / SkillRunner                       │
│  ConnectorManager                                │
│  GardenWriter                                    │
└──────┬──────────────────────────┬───────────────┘
       │                          │
┌──────▼──────┐          ┌────────▼────────┐
│   SKILLS    │          │   CONNECTORS    │
│ input       │          │ google-calendar │
│ process     │          │ telegram        │
│ output      │          │ github          │
│ meta        │          │ (community)     │
└──────┬──────┘          └─────────────────┘
       │
┌──────▼──────────────────────────────────────────┐
│           2ND BRAIN  (Obsidian Vault)            │
│   /seeds  /garden  /actions  /skills            │
└─────────────────────────────────────────────────┘
```

## Key Principles

- **2nd Brain-bound**: All data stays in your Obsidian Vault. Nothing leaves without explicit OutputSkill.
- **Transparent**: Agent's knowledge = Obsidian notes. Agent's actions = logged in `/actions/`.
- **Safe**: Dual safety — Connector connection required + SafeMode approval for dangerous Skills.
- **Extensible**: Everything is a Skill (Input/Process/Output/Meta). YAML + optional Python.

## Quick Start

```bash
# Install dependencies
uv sync --all-extras

# Initialize vault structure
bsage init

# Start the Gateway
bsage run

# List loaded skills
bsage skills

# Run a skill manually
bsage run-skill garden-writer
```

## Development

```bash
# Install with dev dependencies
uv sync --all-extras

# Run tests
uv run pytest bsage/tests/ --cov=bsage -v

# Lint
uv run ruff check bsage/
uv run ruff format --check bsage/
```

## Tech Stack

| Area | Choice |
|------|--------|
| Language | Python 3.11+ |
| Package Manager | uv |
| LLM | litellm (Claude, Ollama, OpenAI, etc.) |
| Config | pydantic-settings |
| Logging | structlog (JSON) |
| Scheduler | APScheduler |
| Gateway | FastAPI + uvicorn |
| 2nd Brain | Obsidian Vault (Markdown) |
