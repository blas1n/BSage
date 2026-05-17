# `bsage.mcp` — Model Context Protocol API surface

BSage treats MCP as a **first-class API surface** alongside REST. Every
MCP tool ships with typed Pydantic input/output schemas, an optional
OpenFGA-backed `required_permission`, and an optional audit event —
mirroring how a FastAPI route is defined. CLI, REST, and MCP all
delegate to the same service-layer functions; no surface is a wrapper
around another.

> **Tier 5 Phase 3a** — MCP tool authorization was migrated from JWT
> `scope`-claim checks to OpenFGA. A tool's `required_permission` is a
> `<product>.<resource>.<action>` dot string run through
> `bsvibe_authz.check_tenant_permission` — the *same* OpenFGA model the
> REST routes' `require_permission` dependency enforces.

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
    required_permission: str | None = None      # OpenFGA dot string
    audit_event: str | None = None              # emitted on success
```

`ToolRegistry` mirrors how a FastAPI router behaves on dispatch:

1. Validate `arguments` against `input_schema` (`ValidationError` →
   `ToolError`, wire-safe).
2. Enforce `required_permission` via
   `bsvibe_authz.check_tenant_permission(ctx.user, permission, fga=...,
   cache=..., settings=...)` — the same OpenFGA check `require_permission`
   runs. Deny raises `ToolScopeDenied`. Permissive (allow) for demo
   sessions and when OpenFGA is unconfigured; an anonymous caller is
   denied on any permissioned tool. `required_permission=None` means the
   tool is open to any authenticated principal.
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
    settings: Any | None = None      # bsvibe_authz.Settings
    user: Any | None = None          # bsvibe-authz principal
    fga: Any | None = None           # OpenFGA client (lazy-resolved if None)
    cache: Any | None = None         # PermissionCache (lazy-resolved if None)
    audit_outbox: AuditOutboxLike | None = None
    request_id: str | None = None
```

`fga` / `cache` / `settings` back the Tier 5 permission check. When the
caller leaves them `None` the dispatcher lazily resolves the
process-wide `bsvibe_authz` singletons — the same OpenFGA client and
30s permission cache the REST `require_permission` dependency uses, so
REST and MCP share one client per process.

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
3. Match `required_permission` to whatever the equivalent REST route
   enforces (e.g. `bsage.config.write` for settings mutations). Every
   value MUST be a row in the bsvibe-authz permission matrix
   (`packages/bsvibe-authz/schema/permission_matrix.yaml`, `bsage:`
   block). Leave it `None` for tools open to any authenticated caller.
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
`ConfigUpdate.model_fields` via `field_validator` before the permission
check or runtime is touched, so typo'd keys raise `ToolError` and the
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

All `required_permission` values are rows in the bsvibe-authz
permission matrix (`bsage:` block).

| Tool | `required_permission` | Audit |
|---|---|---|
| `bsage_skills_list` | `bsage.plugins.read` | — |
| `bsage_skills_run` | `bsage.plugins.execute` | `bsage.mcp.skills_run.invoked` |
| `bsage_plugins_list` | `bsage.plugins.read` | — |
| `bsage_plugins_install` | `bsage.plugins.install` | `bsage.mcp.plugins_install.invoked` |
| `bsage_plugins_enable` | `bsage.config.write` | `bsage.mcp.plugins_enable.invoked` |
| `bsage_plugins_disable` | `bsage.config.write` | `bsage.mcp.plugins_disable.invoked` |
| `bsage_garden_list` | `bsage.vault.read` | — |
| `bsage_canon_list` | `bsage.canonicalization.read` | — |
| `bsage_canon_status` | `bsage.canonicalization.read` | — |
| `bsage_canon_draft` | `bsage.canonicalization.draft` | `bsage.mcp.canon_draft.invoked` |
| `bsage_canon_apply` | `bsage.canonicalization.apply` | `bsage.mcp.canon_apply.invoked` |
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

### Streamable HTTP (`/mcp` on the gateway)
Built in the gateway lifespan via
`bsage.mcp.streamable_http.build_streamable_http_app` and mounted at
`/mcp` — the same transport (and path) the other three BSVibe products
serve.

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /mcp/health` | none | Liveness probe + tool count |
| `/mcp` | bsvibe-authz | Streamable HTTP transport (stateless, JSON response) |

An unauthenticated request to `/mcp` returns `401` + a
`WWW-Authenticate: Bearer resource_metadata="..."` challenge (RFC 9728),
not `404`. `/mcp/health` stays unauthenticated.

Health response:

```json
{ "status": "ok", "server": "bsage", "tool_count": 30 }
```

`tool_count` reflects the **same** `ToolRegistry` the Streamable HTTP
transport serves — domain (9) + canon read (8) + canon mutation (4 if
enabled) + admin (13) + any plugin-bridge tools — so probes are honest,
not stubbed.

### CLI (`bsage mcp`)

```bash
# Boot the stdio transport (Claude Desktop, IDE bridges)
bsage mcp serve --transport stdio

# Boot the gateway + /mcp (Streamable HTTP transport)
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
| `stdio` | Trusted local process. No HTTP request — `ctx.user` is `None`; `required_permission` tools are stdio-unreachable, domain read tools work. |
| Streamable HTTP | The ASGI shim resolves the principal from the per-request `Authorization` header (`bsvibe_authz` opaque → user-JWT → PAT-introspection dispatch) and stashes it on a context-var the dispatcher reads. |

`required_permission` enforcement happens **per tool** inside
`ToolRegistry.call_tool`, running the same OpenFGA
`check_tenant_permission` the REST `require_permission` dependency
uses. Connection-time auth is necessary but not sufficient — each
permissioned tool re-checks the resolved principal against the OpenFGA
model.

> **Principal threading (fixed).** Streamable HTTP carries the
> `Authorization` header on *every* request, so
> `bsage.mcp.streamable_http` resolves the principal per-request and
> threads it into the per-call `ToolContext` via a context-var that
> `bsage.mcp.server._resolve_principal` reads. `ctx.user` is therefore
> the real principal over HTTP and `required_permission` tools
> authorize correctly. (The legacy SSE transport authenticated only
> the *connection* and left `ctx.user = None` — that bug is gone with
> SSE.) The `stdio` transport has no HTTP request, so `ctx.user`
> stays `None` there; that path is a single trusted local process and
> only exposes `required_permission=None` tools in practice.

---

## File map

```
bsage/mcp/
├── api.py             # Tool, ToolContext, ToolRegistry, ToolError
├── server.py          # build_server / build_registry — wires the registry into mcp.server.Server
├── domain_tools.py    # 9 knowledge tools
├── admin_tools.py     # 13 admin tools (mirrors CLI sub-apps)
├── plugin_bridge.py   # dynamic plugin → MCP tool adapter
├── streamable_http.py # Streamable HTTP transport (build_streamable_http_app, principal resolution)
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
- `~/Docs/BSVibe_Phase1_Decisions_2026-05-07.md` — introspection conventions
- Memory `mcp-python-sdk-testing` — test pattern for first-class MCP tools
