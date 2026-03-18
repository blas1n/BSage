# BSage

> *My BSage knows me better than I do.*

Personal AI agent that records everything about you in a 2nd Brain (Obsidian Vault) and proactively acts on it. A transparent, safe alternative to OpenClaw.

## Architecture

```
┌─────────────────────────────────────────────────┐
│              INTERFACE LAYER                     │
│   CLI  │  GUI chatbot  │  Telegram  │  WhatsApp │
│   Slack  │  Discord  │  Signal  │  iMessage    │
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
│  PluginLoader / PluginRunner (14 plugins)        │
│  SkillLoader / SkillRunner (4 skills)            │
│  GardenWriter  │  CredentialStore                │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│            PLUGINS & SKILLS LAYER                │
│  input (data collection + integrations)          │
│  process (analysis, tools, actions)              │
│  output (vault sync backends: git, S3, etc.)     │
└──────────────────────┬──────────────────────────┘
                       │
┌──────▼──────────────────────────────────────────┐
│           2ND BRAIN  (Obsidian Vault)            │
│   /seeds  /garden  /actions  /.bsage             │
│   (ontology, knowledge graph, vectors)           │
└─────────────────────────────────────────────────┘
```

## Key Principles

- **2nd Brain-bound**: All knowledge stored in Obsidian Vault (seeds, garden, ontology graph). Data syncs to external storage only via Output Plugins.
- **Transparent**: Agent knowledge = vault notes. Agent actions = logged in `/actions/`. Full audit trail, always browsable.
- **Safe**: DangerAnalyzer auto-classifies dangerous Plugins (subprocess, external APIs). SafeMode approval gate before execution. User controls which Plugins/Skills to install.
- **Extensible**:
  - **Plugins** (Python): Direct code execution, external API calls, bidirectional channels (input, process, output)
  - **Skills** (Markdown): LLM-only pipeline (GATHER vault context → LLM → APPLY result). Structurally safe, no code execution.

## Quick Start

```bash
# Install dependencies
uv sync --all-extras

# Initialize vault structure
bsage init

# Configure a Plugin (e.g. Telegram)
bsage setup telegram-input

# Start the Gateway (server + REPL)
bsage run

# List loaded Plugins and Skills
bsage plugins
bsage skills

# Run a Skill manually
bsage run-skill insight-linker
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
