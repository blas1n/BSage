# Skill System Rules

## CRITICAL: Plugin vs Skill Dual Architecture

BSage distinguishes two types of execution units.

| | Plugin | Skill |
|---|---|---|
| Location | `plugins/name/plugin.py` | `skills/name.md` |
| Declaration | `@plugin` decorator | YAML frontmatter |
| Execution | Python code runs directly | GATHER → LLM → APPLY pipeline |
| External calls | Yes | No — Vault + LLM only |
| `is_dangerous` | Auto-detected by DangerAnalyzer | None — structurally always safe |
| Notification | `@execute.notify` | N/A |

---

## 1. Plugin Format (`plugins/`)

**Use Plugin when you need code execution, external API calls, or bidirectional notifications.**

```
plugins/
├── telegram-input/
│   └── plugin.py      # @plugin decorator + execute() function
├── calendar-input/
│   └── plugin.py
└── skill-builder/
    └── plugin.py
```

### plugin.py Format

```python
from bsage.plugin import plugin

@plugin(
    name="telegram-input",           # lowercase + hyphens (^[a-z][a-z0-9-]*$)
    version="1.0.0",                 # semver
    category="input",               # input | process | output
    description="Collect Telegram messages and store as seeds.",
    trigger={"type": "webhook"},
    credentials=[
        {"name": "bot_token", "description": "Telegram Bot API token", "required": True},
        {"name": "chat_id",   "description": "Chat ID to monitor",     "required": True},
    ],
)
async def execute(context) -> dict:
    """Inbound: Telegram → Vault."""
    creds = context.credentials
    messages = await fetch_telegram(creds["bot_token"])
    await context.garden.write_seed("telegram", {"messages": messages})
    return {"collected": len(messages)}

@execute.notify  # Optional — register a bidirectional notification handler
async def notify(context) -> dict:
    """Outbound: Vault → Telegram (reverse direction)."""
    creds = context.credentials
    msg = context.input_data["message"]
    await send_telegram(creds["bot_token"], creds["chat_id"], msg)
    return {"sent": True}
```

**Rules:**
- Only `bsage.plugin` may be imported from the `bsage` package — no other internal imports
- External service connections are handled entirely inside the Plugin
- Entry point is always `execute(context)` (async)
- Register a notification handler with `@execute.notify` (bidirectional channels only)

### is_dangerous — Auto-Detection

**Do not declare `is_dangerous` manually. `DangerAnalyzer` determines it automatically.**

```
At plugin load time → AST static analysis
  Detects dangerous module imports:
    httpx, requests, aiohttp, urllib,
    socket, subprocess, telegram,
    smtplib, boto3, etc.
  → is_dangerous = True (automatic)
```

- Cache is invalidated by content hash when plugin code changes → re-analyzed
- Falls back to LLM judgment when AST parsing fails
- Defaults to dangerous (True) when classification is uncertain

---

## 2. Skill Format (`skills/`)

**Use Skill for analysis, transformation, or summarization that only requires LLM and Vault access.**

```
skills/
├── weekly-digest.md   # Single .md file — YAML frontmatter + Markdown body
├── insight-linker.md
└── unfinished-detector.md
```

### *.md Format

```markdown
---
# Required
name: weekly-digest           # lowercase + hyphens (^[a-z][a-z0-9-]*$)
version: 1.0.0                # semver
category: process             # input | process | output
description: "..."            # also used for LLM routing decisions

# Optional — trigger
trigger:
  type: cron                  # cron | on_input | on_demand | write_event
  schedule: "0 9 * * MON"    # when type is cron
  sources: [telegram-input]   # when type is on_input (filter to specific plugins)
  hint: "..."                 # when type is on_demand (guides LLM routing)

# Optional — GATHER phase
read_context:
  - garden/idea
  - garden/insight

# Optional — APPLY phase
output_target: garden         # garden | seeds
output_note_type: insight     # garden note type (default: idea)
output_format: json           # request JSON output from LLM

# Optional
author: string
---

Write the LLM system prompt here as the Markdown body.
```

**Required fields — NEVER omit:**
- `name`, `version`, `category`, `description`

**There is no `is_dangerous` field on Skills.** Markdown Skills can only access the LLM and Vault, so they are structurally always safe.

### YAML-Only Pipeline (GATHER → LLM → APPLY)

1. **GATHER**: Reads Vault notes from `read_context` paths to build context (max 20 notes/dir, 50,000 chars)
2. **LLM**: Calls LLM with the Markdown body as system prompt + vault context + input_data
3. **APPLY**: Saves result to Vault based on `output_target`

```markdown
---
name: weekly-digest
version: 1.0.0
category: process
description: Generate a weekly digest from recent garden notes
trigger:
  type: cron
  schedule: "0 9 * * MON"
read_context:
  - garden/idea
  - garden/insight
output_target: garden
output_note_type: insight
output_format: json
---

Analyze the provided notes and create a structured weekly summary.
Focus on recurring themes, unfinished items, and key insights.
```

---

## 3. Category Definitions

| Category | Role | Trigger examples |
|---|---|---|
| **input** | Active/passive user input collection — external data → Vault seeds | cron, webhook |
| **process** | Tool functionality — analysis, transformation, messaging, tool execution, etc. | on_input, cron, on_demand |
| **output** | Vault sync — Vault → external storage backends | write_event |

- The three categories are **independent and non-sequential** — they are NOT a pipeline (input → process → output)
- `input` = anything that brings user data in (active messages, passive polling, webhooks)
- `process` = anything that acts as a tool (LLM analysis, formatting, sending replies, running actions)
- `output` = mechanical Vault sync to external storage (git, S3, etc.)
- Process can run independently without input (cron, on_demand)
- **There is no `meta` category.** Meta functionality (e.g. SkillBuilder) is implemented as a `process` Plugin

---

## 4. Trigger System

| Type | Target | Behavior |
|---|---|---|
| `cron` | input, process | Schedule-based automatic execution |
| `webhook` | input Plugin | Triggered by `POST /api/webhooks/{name}` HTTP request |
| `on_input` | process | Triggered when an input Plugin result arrives. Filterable by `sources` |
| `write_event` | output | Triggered automatically on any Vault write |
| `on_demand` | process | LLM judgment or user request. `hint` guides routing |

A process entry without a trigger is treated as `on_demand` — the LLM routes it based on `description`.

```yaml
# React to all inputs
trigger:
  type: on_input

# React to a specific input plugin only
trigger:
  type: on_input
  sources: [calendar-input]

# Scheduled process
trigger:
  type: cron
  schedule: "0 9 * * MON"

# Webhook-triggered input
trigger:
  type: webhook
# → Gateway receives it at POST /api/webhooks/{name}
```

---

## 5. SkillContext Interface

Both Plugins and Skills communicate with the Core Engine only through the `context` object.

```python
context.credentials               # dict[str, Any] — auto-injected credentials
context.garden.write_seed(...)    # write to seeds/
context.garden.write_garden(...)  # write to garden/
context.garden.write_action(...)  # write to actions/ log
context.garden.read_notes(...)    # read existing notes
context.llm.chat(...)             # call the LLM
context.config                    # configuration values
context.logger                    # structlog logger
context.input_data                # input payload (when triggered by on_input)
context.notify                    # NotificationInterface — may be None
```

---

## 6. Credential System

**Convention: credential name = plugin/skill name.**

```python
# Declare credentials in plugin.py
@plugin(
    credentials=[
        {"name": "bot_token", "description": "Telegram Bot token", "required": True},
    ]
)
```

- Run `bsage setup <name>` CLI to configure credentials (supports both Plugins and Skills)
- Credentials are auto-injected into `context.credentials` at runtime (PluginRunner resolves from CredentialStore)
- Stored as JSON in the `.credentials/` directory (gitignored)

---

## 7. context.notify — User Notifications (Bidirectional Channel)

Process Plugins/Skills must not call messenger APIs directly. Use `context.notify.send()` — `NotificationRouter` selects the channel automatically.

**Notification channel = reverse direction of an input Plugin.** Registered via `@execute.notify` and auto-discovered.

```python
# In a process plugin or skill
async def execute(context):
    if context.notify:  # may be None when no channel is available
        await context.notify.send("Project 'X' has been stalled for 12 days")
```

```
context.notify.send("msg")
  → NotificationRouter.send()
  → auto-discovers Plugins with _notify_fn in registry
  → runner.run_notify(meta, ctx)
  → ctx.notify = None (prevents recursion)
```

---

## 8. GardenWriter Write Rules

| Directory | Written by | Content |
|---|---|---|
| `seeds/` | After input Plugin execution | Raw collected data |
| `garden/` | After process Plugin/Skill execution | Processed knowledge notes |
| `actions/` | After any Plugin/Skill execution | Agent action log |

**Always use frontmatter:**
```markdown
---
type: idea
status: growing
source: calendar-input
captured_at: 2026-02-22
related: [[BSage]]
---
```

**GardenWriter is built into the core** — no separate skill or plugin needed.
`AgentLoop.on_input()` automatically converts the `items` field from a Plugin result into garden notes.

---

## Verification Checklist

### Before implementing a Plugin:
- [ ] File located at `plugins/{name}/plugin.py`
- [ ] `@plugin` decorator has required fields: name, version, category, description
- [ ] category is one of: input / process / output (no meta)
- [ ] trigger is set appropriately
- [ ] No `bsage` imports other than `bsage.plugin`
- [ ] Entry point is `execute(context)` (async)
- [ ] External services are handled entirely inside the Plugin
- [ ] `context.notify` is checked for None before use
- [ ] Tests use mocked context

### Before implementing a Skill:
- [ ] File located at `skills/{name}.md` (single file)
- [ ] YAML frontmatter has required fields: name, version, category, description
- [ ] category is one of: input / process / output
- [ ] No `is_dangerous` field (Skills do not have one)
- [ ] trigger is set appropriately
- [ ] read_context and output_target are configured appropriately
- [ ] Markdown body contains the system prompt
