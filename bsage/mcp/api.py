"""First-class MCP API primitives — Phase 7 / TASK-002.

This module elevates MCP tools to a first-class API surface alongside
the REST routers in :mod:`bsage.gateway.routes`. Each tool ships with:

* a typed Pydantic ``input_schema`` (drives ListTools' JSON Schema)
* a typed Pydantic ``output_schema`` (validates handler return values)
* an async ``handler`` that talks to the same service layer the REST
  routes use — never the CLI / typer command function
* explicit ``required_scopes`` — checked against the principal resolved
  by the bsvibe-authz 3-way dispatch (bootstrap → opaque → JWT)
* an optional ``audit_event`` — emitted on success via the same
  audit outbox the REST routes use, so every mutating tool is
  observable identically to its REST sibling.

The dispatcher (``ToolRegistry``) deliberately mirrors how FastAPI
routers behave: validate input → enforce scope → run handler →
validate output → audit emit on success.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import structlog
from mcp.types import Tool as McpTool
from pydantic import BaseModel, ValidationError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ToolError(Exception):
    """Generic dispatcher error.

    Wire-safe — must never carry implementation details from the
    underlying handler. The dispatcher catches every internal exception
    and re-raises a ``ToolError`` with a sanitised message.
    """


class ToolScopeDenied(ToolError):  # noqa: N818 — wire-stable public API name
    """Raised when the principal lacks one or more ``required_scopes``."""


# ---------------------------------------------------------------------------
# Audit outbox protocol — mirrors the surface used by REST routes (see
# ``bsage.garden.audit_outbox.AiosqliteAuditOutbox``) without forcing the
# tooling layer to depend on the concrete implementation.
# ---------------------------------------------------------------------------
@runtime_checkable
class AuditOutboxLike(Protocol):
    is_open: bool

    async def insert_event(self, event: Any) -> None:  # pragma: no cover - protocol
        ...


# ---------------------------------------------------------------------------
# Context + Tool primitive
# ---------------------------------------------------------------------------
@dataclass
class ToolContext:
    """Runtime context handed to every tool handler.

    ``user`` mirrors :class:`bsvibe_authz.User`. The dispatcher never
    inspects internal fields directly — only ``user.scope``,
    ``user.id``, ``user.email``, ``user.is_service``,
    ``user.active_tenant_id`` — so a duck-typed test fixture works
    without dragging in the real authz package.
    """

    user: Any | None = None
    audit_outbox: AuditOutboxLike | None = None
    state: Any | None = None
    settings: Any | None = None
    request_id: str | None = None


ToolHandler = Callable[[BaseModel, ToolContext], Awaitable[BaseModel]]


@dataclass
class Tool:
    """First-class MCP tool definition."""

    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    handler: ToolHandler
    required_scopes: list[str] = field(default_factory=list)
    audit_event: str | None = None


# ---------------------------------------------------------------------------
# Registry / dispatcher
# ---------------------------------------------------------------------------
class ToolRegistry:
    """In-process registry + dispatcher for first-class MCP tools.

    Mounted from both transports (HTTP ``/mcp``, stdio ``bsage mcp serve
    --transport stdio``) so that domain + admin tools share one
    catalog.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # -- registration -------------------------------------------------------
    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    # -- ListTools ----------------------------------------------------------
    def list_tools(self) -> list[McpTool]:
        """Return MCP-wire ``Tool`` definitions for every registered tool."""
        return [
            McpTool(
                name=t.name,
                description=t.description,
                inputSchema=_pydantic_to_json_schema(t.input_schema),
            )
            for t in self._tools.values()
        ]

    # -- CallTool -----------------------------------------------------------
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        ctx: ToolContext,
    ) -> dict[str, Any]:
        """Validate args → enforce scope → run → validate output → audit emit.

        Returns the validated output as a JSON-safe ``dict``. The MCP
        transport wraps that into a ``TextContent`` payload — that
        translation lives in the transport layer, not here.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool: {name}")

        # 1. Input validation.
        try:
            args_model = tool.input_schema.model_validate(arguments or {})
        except ValidationError as exc:
            # Pydantic errors are user-facing (caller-visible) and safe
            # to surface — they describe the schema violation, not
            # internal state.
            raise ToolError(f"invalid arguments for {name}: {exc.errors()}") from exc

        # 2. Scope enforcement.
        _enforce_scopes(tool, ctx)

        # 3. Handler invocation — wrap any internal failure so the wire
        #    response never leaks implementation detail.
        try:
            output = await tool.handler(args_model, ctx)
        except ToolError:
            # Handlers may raise dispatcher-shaped errors directly;
            # propagate them unchanged.
            raise
        except Exception as exc:  # noqa: BLE001 — boundary translation
            logger.exception(
                "mcp_tool_handler_failed",
                tool=name,
                error_type=type(exc).__name__,
            )
            raise ToolError(f"tool {name!r} failed") from exc

        # 4. Output validation.
        try:
            output_model = tool.output_schema.model_validate(output)
        except ValidationError as exc:
            logger.warning(
                "mcp_tool_output_invalid",
                tool=name,
                errors=exc.errors(),
            )
            raise ToolError(f"tool {name!r} produced invalid output") from exc

        # 5. Audit emit (best-effort, never breaks the call).
        if tool.audit_event is not None:
            await _safe_audit_emit(tool, ctx)

        return output_model.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pydantic_to_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Render a Pydantic model's JSON Schema for the MCP wire."""
    schema = model.model_json_schema()
    # Pydantic returns a $defs-style schema; keep it intact — the MCP
    # SDK's clients (and Claude Desktop) follow JSON Schema 2020-12.
    if "type" not in schema:
        schema["type"] = "object"
    return schema


def _enforce_scopes(tool: Tool, ctx: ToolContext) -> None:
    """Check that ctx.user carries every scope ``tool.required_scopes`` lists.

    Mirrors :func:`bsage.gateway.authz.require_bsage_permission` semantics:
    a tool with no required scopes is anonymous-friendly; a tool with
    required scopes denies missing/anonymous principals.
    """
    if not tool.required_scopes:
        return
    user = ctx.user
    if user is None:
        raise ToolScopeDenied(f"tool {tool.name!r} requires authentication")
    user_scopes = set(getattr(user, "scope", None) or [])
    missing = [s for s in tool.required_scopes if s not in user_scopes]
    if missing:
        raise ToolScopeDenied(
            f"tool {tool.name!r} requires scopes: {missing}",
        )


async def _safe_audit_emit(tool: Tool, ctx: ToolContext) -> None:
    """Emit ``tool.audit_event`` via the audit outbox.

    Failures are swallowed — identical contract to
    :func:`bsage.garden.audit_outbox.safe_emit` so an outage in the
    audit pipeline cannot break a successful tool call.

    Sensitive arguments are NOT echoed in the event payload — only the
    tool name + actor land on the wire. Handlers wanting richer audit
    payloads should emit their own typed events from inside the
    handler body, identical to how REST routes do.
    """
    outbox = ctx.audit_outbox
    if outbox is None or not getattr(outbox, "is_open", False):
        return
    try:
        from bsvibe_audit import AuditActor, AuditResource
        from bsvibe_audit.events import AuditEventBase

        actor = _actor_from_user(ctx.user, AuditActor)
        event = AuditEventBase(
            event_type=tool.audit_event or f"bsage.mcp.{tool.name}.invoked",
            actor=actor,
            tenant_id=getattr(ctx.user, "active_tenant_id", None),
            resource=AuditResource(type="mcp_tool", id=tool.name),
            data={"tool": tool.name},
        )
        await outbox.insert_event(event)
    except Exception:  # noqa: BLE001 - audit must never break the call
        logger.warning(
            "mcp_audit_emit_failed",
            tool=tool.name,
            event_type=tool.audit_event,
            exc_info=True,
        )


def _actor_from_user(user: Any, actor_cls: type) -> Any:
    """Build an AuditActor from a principal — system fallback when None."""
    if user is None:
        return actor_cls(type="system", id="bsage")
    pid = getattr(user, "id", None) or "anonymous"
    email = getattr(user, "email", None)
    actor_type = "service" if getattr(user, "is_service", False) else "user"
    return actor_cls(
        type=actor_type,
        id=str(pid),
        email=email if isinstance(email, str) else None,
    )


__all__ = [
    "AuditOutboxLike",
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolHandler",
    "ToolRegistry",
    "ToolScopeDenied",
]
