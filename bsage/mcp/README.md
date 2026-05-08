# `bsage.mcp` — Model Context Protocol API surface

BSage treats MCP as a **first-class API surface** alongside REST. Every
MCP tool ships with typed Pydantic input/output schemas, explicit
required scopes, and an optional audit event — mirroring how a FastAPI
route is defined. CLI, REST, and MCP all delegate to the same
service-layer functions; no surface is a wrapper around another.

This document covers:

1. The first-class `Tool` primitive
2. How to add a new tool
3. The shipped catalog (domain, canonicalization, admin, plugin bridge)
4. HTTP `/mcp` endpoints and the `bsage mcp` CLI launcher
5. Auth resolution

---

## 1. First-class `Tool` primitive

Defined in `bsage/mcp/api.py`:

```python
@dataclass
class Tool:
    name: str                                   # e.g. "bsage_settings_set"
    description: str
    input_schema: type[pydantic.BaseModel]      # drives ListTools' JSON Schema
    output_schema: type[pydantic.BaseModel]     # validates handler return
    handler: Callable[[BaseModel, ToolContext], Awaitable[BaseModel | dict]]
    required_scopes: list[str] = []             # checked vs. principal
    audit_event: str | None = None              # emitted on success
```

`ToolRegistry` mirrors how a FastAPI router behaves on dispatch:

1. Validate `arguments` against `input_schema` (`ValidationError` →
   `ToolError`, wire-safe).
2. Enforce every entry in `required_scopes` against
   `ctx.user.scopes` — missing scope raises `ToolScopeDenied`.
3. Run `handler(input_model, ctx)`.
4. Validate the return value against `output_schema` (handlers may
   return either a model instance or a dict; `model_config =
   ConfigDict(extra="allow")` on output schemas keeps error envelopes
   like `{"error": "not_found"}` round-trippable).
5. If `audit_event` is set, emit a best-effort
   `bsvibe_audit.AuditEventBase` via `ctx.audit_outbox`. Audit
   failures are swallowed — they never break the call.

Any unexpected handler exception is caught, logged with `error_type`
only (no stack content goes to the client), and re-raised as a
sanitised `ToolError(f"tool {name!r} failed")`. Internal detail never
reaches the wire.

### `ToolContext`

```python
@dataclass
class ToolContext:
    state: Any                       # AppState (DB, vault, services)
    settings: Settings | None = None
    user: Any | None = None          # bsvibe-authz principal
    audit_outbox: AuditOutboxLike | None = None
    request_id: str | None = None
```

Handlers should call the same service-layer function the REST route
calls — never the Typer command function and never an HTTP client
back to ourselves.

---

## 2. Adding a new tool

1. Define Pydantic input + output models. Reuse the models the REST
   route / service layer already exposes when one exists.
2. Write an `async def handler(inp: InputModel, ctx: ToolContext) ->
   OutputModel` that calls the service layer (e.g.
   `ctx.state.canon_service.apply(...)`). **Do not** call the CLI or
   HTTP — direct service call only.
3. Match `required_scopes` to whatever the equivalent REST route
   enforces (e.g. `bsage.config.write` for settings mutations,
   `bsage:knowledge:read` for query tools).
4. For mutating tools, set `audit_event="bsage.mcp.<area>.<verb>.invoked"`
   to mirror the REST audit event.
5. Register the tool in the appropriate module's `register_*` helper:
   - Domain knowledge tools → `bsage/mcp/domain_tools.py`
   - Canonicalization tools → `bsage/garden/canonicalization/mcp_tools.py`
   - Admin tools (mirrors a CLI sub-app action) → `bsage/mcp/admin_tools.py`
6. Write a test under `bsage/tests/test_*.py`. Per memory
   `mcp-python-sdk-testing`, never spawn subprocesses — extract
   `server.request_handlers` and invoke `ListToolsRequest` /
   `CallToolRequest` directly. Result is wrapped in `ServerResult.root`.
7. Naming: admin tools follow `bsage_<subapp>_<action>` (e.g.
   `bsage_canon_apply`). Domain/legacy tools keep their existing
   names so the contract is preserved.

### Sensitive arguments

Per project rules and `python-security.md`: never log argument
**values** for tools whose payloads might carry secrets (settings
writes, credentials). The dispatcher logs only field names and
`error_type`. `bsage_settings_set` validates the `key` against
`ConfigUpdate.model_fields` via `field_validator` before scope or
runtime is touched, so typo'd keys raise `ToolError` and the
sensitive value never lands in logs.

---

## 3. Shipped catalog

Total: **34 tools** when `mcp_canon_mutation_enabled=True`, plus any
plugins that opt in via `mcp_exposed=True`.

### Domain (9 tools — `bsage/mcp/domain_tools.py`)
Knowledge graph queries against the vault.

| Tool | Audit | Purpose |
|---|---|---|
| `search_knowledge` | — | Hybrid search over notes |
| `get_note` | — | Fetch a single note by id/slug |
| `get_graph_context` | — | N-hop neighborhood |
| `list_recent` | — | Recent notes |
| `list_by_tag` | — | Notes filtered by tag |
| `list_tags` | — | Tag inventory |
| `browse_communities` | — | Cluster summaries |
| `browse_entity` | — | Entity-centric view |
| `create_note` | `bsage.mcp.create_note.invoked` | Mutating |

### Canonicalization (8 read + 4 mutation — `bsage/garden/canonicalization/mcp_tools.py`)
Mutation tools are gated by `settings.mcp_canon_mutation_enabled`
(default OFF, per Handoff §15.2).

Read: `canon_*_list`, `canon_*_get`, `canon_proposals_*`, `canon_status`.
Mutation (audit-emitting): `canon_action_draft`, `canon_action_apply`,
`canon_action_approve`, `canon_action_reject` →
`bsage.mcp.canon.{action_draft.created, action.applied,
action.approved, action.rejected}`.

### Admin (13 tools — `bsage/mcp/admin_tools.py`)
One per CLI sub-app action. Direct service-layer calls, never CLI/HTTP.

| Tool | Required scope | Audit |
|---|---|---|
| `bsage_skills_list` | `bsage.skills.read` | — |
| `bsage_skills_run` | `bsage.skills.write` | `bsage.mcp.skills_run.invoked` |
| `bsage_plugins_list` | `bsage.plugins.read` | — |
| `bsage_plugins_install` | `bsage.plugins.write` | `bsage.mcp.plugins_install.invoked` |
| `bsage_plugins_enable` | `bsage.plugins.write` | `bsage.mcp.plugins_enable.invoked` |
| `bsage_plugins_disable` | `bsage.plugins.write` | `bsage.mcp.plugins_disable.invoked` |
| `bsage_garden_list` | `bsage.garden.read` | — |
| `bsage_canon_list` | `bsage.canon.read` | — |
| `bsage_canon_status` | `bsage.canon.read` | — |
| `bsage_canon_draft` | `bsage.canon.write` | `bsage.mcp.canon_draft.invoked` |
| `bsage_canon_apply` | `bsage.canon.write` | `bsage.mcp.canon_apply.invoked` |
| `bsage_settings_get` | `bsage.config.read` | — |
| `bsage_settings_set` | `bsage.config.write` | `bsage.mcp.settings_set.invoked` |

`bsage run` is intentionally **excluded** — long-running, not safe
to expose as a synchronous tool call.

### Plugin bridge (dynamic)
Any plugin whose `@plugin` decorator carries `mcp_exposed=True` shows
up automatically through `bsage/mcp/plugin_bridge.py`. Schemas are
author-controlled at decorator time, so plugins live outside the
typed registry — they're bridged on demand.

---

## 4. Transports

### HTTP (`/mcp` on the gateway)
Mounted in the gateway lifespan via `bsage.mcp.sse.create_sse_routes`:

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /mcp/health` | none | Liveness probe + tool count |
| `GET /mcp/sse` | bsvibe-authz | SSE event stream (server → client) |
| `POST /mcp/messages/{path}` | bsvibe-authz | SSE POST half (client → server) |

Health response:

```json
{ "status": "ok", "server": "bsage", "tool_count": 30 }
```

`tool_count` reflects the **same** `ToolRegistry` the SSE transport
serves — domain (9) + canon read (8) + canon mutation (4 if enabled)
+ admin (13) + any plugin-bridge tools — so probes are honest, not
stubbed.

### CLI (`bsage mcp`)

```bash
# Boot the stdio transport (Claude Desktop, IDE bridges)
bsage mcp serve --transport stdio

# Boot the gateway + /mcp/sse (HTTP transport)
bsage mcp serve --transport http --host 0.0.0.0 --port 8000

# Inspect the catalog without booting any transport
bsage mcp list-tools --output json
```

`--dry-run` (the global CLI flag) short-circuits **before** either
transport boots. `list-tools` builds an in-process `AppState` and
registry; it never opens DB / vault / LLM connections, so the catalog
is fast and offline-friendly.

The `bsage-mcp` console script (entry point) also points at
`bsage.mcp.stdio.run_stdio_server` for legacy Claude Desktop configs.

---

## 5. Auth resolution

| Transport | Mechanism |
|---|---|
| `stdio` | Trusted local process. Principal is read from env via `BSV_BOOTSTRAP_TOKEN` (verified by bsvibe-authz `verify_bootstrap_token`). |
| `http` (SSE) | `state.get_current_user(request)` — bsvibe-authz 3-way dispatch (bootstrap token → opaque introspection → JWT). |

EventSource cannot send `Authorization` headers, so `GET /mcp/sse`
also accepts `?token=<bearer>` and injects it as a `Bearer` header
before delegating to the same dispatcher. Documented under memory
`eventsource-sse-auth-trap`.

`required_scopes` enforcement happens **per tool** inside
`ToolRegistry.call_tool`, identical to how `require_scope` guards a
REST route. Connection-time auth is necessary but not sufficient —
each mutating tool re-checks scopes against the resolved principal.

---

## File map

```
bsage/mcp/
├── api.py             # Tool, ToolContext, ToolRegistry, ToolError
├── server.py          # build_server / build_registry — wires the registry into mcp.server.Server
├── domain_tools.py    # 9 knowledge tools
├── admin_tools.py     # 13 admin tools (mirrors CLI sub-apps)
├── plugin_bridge.py   # dynamic plugin → MCP tool adapter
├── sse.py             # FastAPI router: /mcp/health, /mcp/sse, /mcp/messages/
├── stdio.py           # stdio transport entry (run_stdio_server)
└── README.md          # this file

bsage/garden/canonicalization/mcp_tools.py
                       # 8 read + 4 mutation canon tools (gated)

bsage/cli/commands/mcp.py
                       # `bsage mcp serve|list-tools` Typer sub-app
```

---

## See also

- `~/Docs/BSVibe_AI_Native_Control_Plane_Plan_2026-05-06.md` — overall plan
- `~/Docs/BSVibe_Phase1_Decisions_2026-05-07.md` — bootstrap_token + introspection conventions
- Memory `mcp-python-sdk-testing` — test pattern for first-class MCP tools
- Memory `eventsource-sse-auth-trap` — `?token=` fallback for SSE auth
