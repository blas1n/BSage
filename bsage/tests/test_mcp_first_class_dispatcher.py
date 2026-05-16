"""Tests for the first-class MCP Tool primitive + dispatcher.

Phase 7 / TASK-002 — MCP becomes a first-class API surface where each
tool has explicit Pydantic input/output schemas, scope guards, and an
optional audit event, mirroring REST router definitions.

Tests use the in-process pattern (memory `mcp-python-sdk-testing`):
ToolRegistry exposes ``list_tools()`` returning ``mcp.types.Tool`` and
``call_tool(name, args, ctx)`` returning the validated output model
serialised as JSON-text content. No subprocesses spawned.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, Field

from bsage.mcp.api import (
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    ToolScopeDenied,
)


# ---------------------------------------------------------------------------
# Sample tool models
# ---------------------------------------------------------------------------
class EchoIn(BaseModel):
    message: str = Field(..., min_length=1)


class EchoOut(BaseModel):
    echoed: str


class CreateNoteIn(BaseModel):
    title: str
    body: str = ""


class CreateNoteOut(BaseModel):
    id: str
    title: str


class _FakeUser:
    def __init__(
        self,
        *,
        id: str = "user-1",  # noqa: A002 — mirrors bsvibe_authz.User.id
        active_tenant_id: str | None = "tenant-a",
        is_service: bool = False,
    ) -> None:
        self.id = id
        self.active_tenant_id = active_tenant_id
        self.is_service = is_service
        self.is_demo = False
        self.app_metadata: dict[str, object] = {}
        self.email = None


class _FakeFga:
    """OpenFGA client stub — fixed allow/deny verdict."""

    def __init__(self, *, allowed: bool) -> None:
        self._allowed = allowed

    async def check(self, user: str, relation: str, object_: str) -> bool:
        return self._allowed

    async def write_tuple(self, user: str, relation: str, object_: str) -> None:
        return None


def _permissive_settings() -> SimpleNamespace:
    """OpenFGA unconfigured — ``check_tenant_permission`` is permissive."""
    return SimpleNamespace(openfga_api_url="", permission_cache_ttl_s=30)


def _enforcing_settings() -> SimpleNamespace:
    """OpenFGA configured — the real check runs against the fake fga."""
    return SimpleNamespace(openfga_api_url="http://openfga.test", permission_cache_ttl_s=30)


@pytest.fixture()
def ctx_admin() -> ToolContext:
    # Permissive authz settings → an authenticated principal passes every
    # ``required_permission`` tool.
    from bsvibe_authz import PermissionCache

    return ToolContext(
        user=_FakeUser(id="admin"),
        audit_outbox=AsyncMock(),
        state=None,
        settings=_permissive_settings(),
        fga=_FakeFga(allowed=True),
        cache=PermissionCache(ttl_s=30),
    )


@pytest.fixture()
def ctx_denied() -> ToolContext:
    # OpenFGA configured + fake fga denies → permissioned tools 403.
    from bsvibe_authz import PermissionCache

    return ToolContext(
        user=_FakeUser(id="user-1"),
        audit_outbox=AsyncMock(),
        state=None,
        settings=_enforcing_settings(),
        fga=_FakeFga(allowed=False),
        cache=PermissionCache(ttl_s=30),
    )


@pytest.fixture()
def ctx_anon() -> ToolContext:
    return ToolContext(
        user=None,
        audit_outbox=None,
        state=None,
        settings=_permissive_settings(),
    )


# ---------------------------------------------------------------------------
# Sample handlers
# ---------------------------------------------------------------------------
async def _echo_handler(args: EchoIn, ctx: ToolContext) -> EchoOut:
    return EchoOut(echoed=args.message)


async def _create_note_handler(args: CreateNoteIn, ctx: ToolContext) -> CreateNoteOut:
    return CreateNoteOut(id="note-42", title=args.title)


async def _broken_handler(args: EchoIn, ctx: ToolContext) -> EchoOut:
    # Returns wrong type intentionally to exercise output validation.
    return {"echoed": 12345}  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# ToolRegistry.list_tools
# ---------------------------------------------------------------------------
class TestListTools:
    def test_list_tools_returns_mcp_tool_with_json_schema(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="Echoes the message back",
                input_schema=EchoIn,
                output_schema=EchoOut,
                handler=_echo_handler,
            )
        )
        tools = reg.list_tools()
        assert len(tools) == 1
        t = tools[0]
        assert t.name == "echo"
        assert "message" in t.inputSchema["properties"]
        assert t.inputSchema["required"] == ["message"]

    def test_register_duplicate_name_raises(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=EchoIn,
                output_schema=EchoOut,
                handler=_echo_handler,
            )
        )
        with pytest.raises(ValueError):
            reg.register(
                Tool(
                    name="echo",
                    description="dup",
                    input_schema=EchoIn,
                    output_schema=EchoOut,
                    handler=_echo_handler,
                )
            )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
class TestSchemaValidation:
    @pytest.mark.asyncio
    async def test_invalid_args_raises_tool_error(self, ctx_admin: ToolContext) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=EchoIn,
                output_schema=EchoOut,
                handler=_echo_handler,
            )
        )
        # ``message`` is required + min_length=1 — empty string fails
        with pytest.raises(ToolError):
            await reg.call_tool("echo", {"message": ""}, ctx_admin)

    @pytest.mark.asyncio
    async def test_unknown_tool_raises(self, ctx_admin: ToolContext) -> None:
        reg = ToolRegistry()
        with pytest.raises(ToolError):
            await reg.call_tool("missing", {}, ctx_admin)

    @pytest.mark.asyncio
    async def test_handler_output_validated(self, ctx_admin: ToolContext) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="broken",
                description="x",
                input_schema=EchoIn,
                output_schema=EchoOut,
                handler=_broken_handler,
            )
        )
        with pytest.raises(ToolError):
            await reg.call_tool("broken", {"message": "hi"}, ctx_admin)

    @pytest.mark.asyncio
    async def test_valid_call_returns_output_model_dump(self, ctx_admin: ToolContext) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=EchoIn,
                output_schema=EchoOut,
                handler=_echo_handler,
            )
        )
        result = await reg.call_tool("echo", {"message": "hello"}, ctx_admin)
        assert result == {"echoed": "hello"}


# ---------------------------------------------------------------------------
# Permission enforcement — Tier 5: OpenFGA ``check_tenant_permission``.
# ---------------------------------------------------------------------------
class TestPermissionEnforcement:
    @pytest.mark.asyncio
    async def test_required_permission_passes_in_permissive_mode(
        self, ctx_admin: ToolContext
    ) -> None:
        # OpenFGA unconfigured → permissive: any authenticated principal
        # passes a ``required_permission`` tool.
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="create_note",
                description="x",
                input_schema=CreateNoteIn,
                output_schema=CreateNoteOut,
                handler=_create_note_handler,
                required_permission="bsage.knowledge.write",
            )
        )
        result = await reg.call_tool("create_note", {"title": "T"}, ctx_admin)
        assert result["id"] == "note-42"

    @pytest.mark.asyncio
    async def test_openfga_deny_raises_denied(self, ctx_denied: ToolContext) -> None:
        # OpenFGA configured + fga.check → False ⇒ tool is denied.
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="create_note",
                description="x",
                input_schema=CreateNoteIn,
                output_schema=CreateNoteOut,
                handler=_create_note_handler,
                required_permission="bsage.knowledge.write",
            )
        )
        with pytest.raises(ToolScopeDenied):
            await reg.call_tool("create_note", {"title": "T"}, ctx_denied)

    @pytest.mark.asyncio
    async def test_no_user_with_required_permission_raises(self, ctx_anon: ToolContext) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="create_note",
                description="x",
                input_schema=CreateNoteIn,
                output_schema=CreateNoteOut,
                handler=_create_note_handler,
                required_permission="bsage.knowledge.write",
            )
        )
        with pytest.raises(ToolScopeDenied):
            await reg.call_tool("create_note", {"title": "T"}, ctx_anon)

    @pytest.mark.asyncio
    async def test_no_required_permission_allows_anon(self, ctx_anon: ToolContext) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=EchoIn,
                output_schema=EchoOut,
                handler=_echo_handler,
            )
        )
        result = await reg.call_tool("echo", {"message": "hi"}, ctx_anon)
        assert result == {"echoed": "hi"}

    @pytest.mark.asyncio
    async def test_service_principal_passes_in_permissive_mode(self) -> None:
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="create_note",
                description="x",
                input_schema=CreateNoteIn,
                output_schema=CreateNoteOut,
                handler=_create_note_handler,
                required_permission="bsage.knowledge.write",
            )
        )
        ctx = ToolContext(
            user=_FakeUser(id="service:bsnexus", is_service=True),
            audit_outbox=AsyncMock(),
            state=None,
            settings=_permissive_settings(),
        )
        result = await reg.call_tool("create_note", {"title": "T"}, ctx)
        assert result["title"] == "T"

    @pytest.mark.asyncio
    async def test_no_active_tenant_denied_when_openfga_configured(self) -> None:
        # A principal with no active tenant cannot resolve a ``tenant:<id>``
        # object — denied once OpenFGA is configured even if fga allows.
        from bsvibe_authz import PermissionCache

        reg = ToolRegistry()
        reg.register(
            Tool(
                name="create_note",
                description="x",
                input_schema=CreateNoteIn,
                output_schema=CreateNoteOut,
                handler=_create_note_handler,
                required_permission="bsage.knowledge.write",
            )
        )
        ctx = ToolContext(
            user=_FakeUser(id="user-1", active_tenant_id=None),
            audit_outbox=AsyncMock(),
            state=None,
            settings=_enforcing_settings(),
            fga=_FakeFga(allowed=True),
            cache=PermissionCache(ttl_s=30),
        )
        with pytest.raises(ToolScopeDenied):
            await reg.call_tool("create_note", {"title": "T"}, ctx)


# ---------------------------------------------------------------------------
# Audit emit
# ---------------------------------------------------------------------------
class _RecordingOutbox:
    """Stand-in for AiosqliteAuditOutbox — records inserted events."""

    def __init__(self) -> None:
        self.is_open = True
        self.events: list[Any] = []

    async def insert_event(self, event: Any) -> None:
        self.events.append(event)


class TestAuditEmit:
    @pytest.mark.asyncio
    async def test_audit_event_emitted_on_success(self) -> None:
        outbox = _RecordingOutbox()
        ctx = ToolContext(
            user=_FakeUser(id="admin"),
            audit_outbox=outbox,
            state=None,
            settings=_permissive_settings(),
        )
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="create_note",
                description="x",
                input_schema=CreateNoteIn,
                output_schema=CreateNoteOut,
                handler=_create_note_handler,
                required_permission="bsage.knowledge.write",
                audit_event="bsage.mcp.create_note.invoked",
            )
        )
        await reg.call_tool("create_note", {"title": "T"}, ctx)
        assert len(outbox.events) == 1
        ev = outbox.events[0]
        assert ev.event_type == "bsage.mcp.create_note.invoked"
        assert ev.actor.id == "admin"

    @pytest.mark.asyncio
    async def test_audit_not_emitted_when_handler_raises(self) -> None:
        outbox = _RecordingOutbox()
        ctx = ToolContext(
            user=_FakeUser(id="admin"),
            audit_outbox=outbox,
            state=None,
            settings=_permissive_settings(),
        )

        async def boom(args: EchoIn, _ctx: ToolContext) -> EchoOut:
            raise RuntimeError("nope")

        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=EchoIn,
                output_schema=EchoOut,
                handler=boom,
                audit_event="bsage.mcp.echo.invoked",
            )
        )
        with pytest.raises(ToolError):
            await reg.call_tool("echo", {"message": "x"}, ctx)
        assert outbox.events == []

    @pytest.mark.asyncio
    async def test_no_audit_event_when_field_absent(self) -> None:
        outbox = _RecordingOutbox()
        ctx = ToolContext(
            user=_FakeUser(id="reader"),
            audit_outbox=outbox,
            state=None,
            settings=_permissive_settings(),
        )
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=EchoIn,
                output_schema=EchoOut,
                handler=_echo_handler,
            )
        )
        await reg.call_tool("echo", {"message": "hi"}, ctx)
        assert outbox.events == []

    @pytest.mark.asyncio
    async def test_audit_emit_failure_does_not_break_call(self) -> None:
        class BrokenOutbox:
            is_open = True

            async def insert_event(self, event: Any) -> None:
                raise RuntimeError("audit down")

        ctx = ToolContext(
            user=_FakeUser(id="admin"),
            audit_outbox=BrokenOutbox(),
            state=None,
            settings=_permissive_settings(),
        )
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="create_note",
                description="x",
                input_schema=CreateNoteIn,
                output_schema=CreateNoteOut,
                handler=_create_note_handler,
                required_permission="bsage.knowledge.write",
                audit_event="bsage.mcp.create_note.invoked",
            )
        )
        # Audit emit failure is swallowed — call still succeeds.
        result = await reg.call_tool("create_note", {"title": "T"}, ctx)
        assert result["id"] == "note-42"


# ---------------------------------------------------------------------------
# Error semantics — leak nothing into the wire format.
# ---------------------------------------------------------------------------
class TestErrorTranslation:
    @pytest.mark.asyncio
    async def test_handler_runtime_error_wrapped_as_tool_error(
        self, ctx_admin: ToolContext
    ) -> None:
        async def boom(args: EchoIn, _ctx: ToolContext) -> EchoOut:
            raise RuntimeError("internal db state")

        reg = ToolRegistry()
        reg.register(
            Tool(
                name="echo",
                description="x",
                input_schema=EchoIn,
                output_schema=EchoOut,
                handler=boom,
            )
        )
        with pytest.raises(ToolError) as excinfo:
            await reg.call_tool("echo", {"message": "hi"}, ctx_admin)
        # Error MESSAGE stays redacted (can carry DB columns / paths / secrets).
        assert "internal db state" not in str(excinfo.value)
        # But the exception CLASS NAME is surfaced (Round 4 Finding 21) so
        # an LLM caller can distinguish error categories and self-correct.
        # Class names are public stdlib/lib types — not implementation detail.
        assert "RuntimeError" in str(excinfo.value)
