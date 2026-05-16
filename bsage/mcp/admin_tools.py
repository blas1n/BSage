"""First-class :class:`bsage.mcp.api.Tool` definitions for the admin
catalog — one tool per CLI sub-app action under ``bsage/cli/commands/``.

Naming: ``bsage_<subapp>_<action>``. Each tool ships with explicit
Pydantic ``input_schema`` / ``output_schema`` models. Handlers call the
same in-process service layer the REST routes use (loaders,
``runtime_config``, ``vault``, ``canon_service``, ``agent_loop``) — they
never shell out to the CLI or to HTTP. CLI / REST / MCP all share one
service layer.

``required_permission`` carries a ``bsage.<resource>.<action>`` dot
string identical to the REST routes' ``require_permission`` argument so
the MCP surface enforces the *same* OpenFGA model as the gateway routes
(Tier 5 Phase 3a). Mutating tools declare ``audit_event`` so every state
change is observable identically to its REST sibling.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bsage.gateway.routes import ConfigUpdate
from bsage.mcp.api import Tool, ToolContext, ToolError, ToolRegistry

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_VALID_SET_KEYS: frozenset[str] = frozenset(ConfigUpdate.model_fields.keys())


def _validate_entry_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ToolError(
            f"invalid entry name: {name!r} (must match [a-z][a-z0-9-]*)",
        )
    return name


class _PermissiveModel(BaseModel):
    """Output base — preserve handler-supplied extras on the wire."""

    model_config = ConfigDict(extra="allow")


def _meta_to_dict(
    meta: Any,
    danger_map: dict[str, bool] | None,
    configured_services: list[str] | None,
    disabled_entries: list[str] | None,
) -> dict[str, Any]:
    """JSON-safe serialisation of a Plugin/Skill meta — mirrors
    :func:`bsage.gateway.routes._meta_to_dict` so the admin MCP catalog
    and ``GET /api/plugins`` share one wire shape."""
    creds = meta.credentials
    if isinstance(creds, list):
        has_credentials = bool(creds)
    elif isinstance(creds, dict):
        has_credentials = bool(creds.get("fields"))
    else:
        has_credentials = False
    credentials_configured = meta.name in (configured_services or []) if has_credentials else True
    if has_credentials and not credentials_configured:
        enabled = False
    else:
        enabled = meta.name not in (disabled_entries or [])
    return {
        "name": meta.name,
        "version": meta.version,
        "category": meta.category,
        "is_dangerous": (danger_map or {}).get(meta.name, False),
        "description": meta.description,
        "has_credentials": has_credentials,
        "credentials_configured": credentials_configured,
        "enabled": enabled,
        "trigger": meta.trigger,
        "entry_type": "plugin" if hasattr(meta, "_execute_fn") else "skill",
        "input_schema": getattr(meta, "input_schema", None),
        "mcp_exposed": bool(getattr(meta, "mcp_exposed", False)),
    }


def _settings_snapshot(state: Any) -> dict[str, Any]:
    rc = state.runtime_config
    snap = dict(rc.snapshot())
    snap["has_llm_api_key"] = bool(rc.llm_api_key)
    snap["has_embedding_api_key"] = bool(rc.embedding_api_key)
    snap["index_available"] = bool(state.retriever.index_available)
    return snap


# ---------------------------------------------------------------------------
# skills.list
# ---------------------------------------------------------------------------
class SkillsListInput(BaseModel):
    pass


class SkillsListOutput(_PermissiveModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


async def _h_skills_list(args: SkillsListInput, ctx: ToolContext) -> dict[str, Any]:
    state = ctx.state
    registry = await state.skill_loader.load_all()
    configured = state.credential_store.list_services()
    disabled = state.runtime_config.disabled_entries
    items = [
        _meta_to_dict(meta, state.danger_map, configured, disabled) for meta in registry.values()
    ]
    return {"items": items}


# ---------------------------------------------------------------------------
# skills.run  (mutating — audit_event)
# ---------------------------------------------------------------------------
class SkillsRunInput(BaseModel):
    name: str
    input: dict[str, Any] | None = None


class SkillsRunOutput(_PermissiveModel):
    name: str
    result: Any = None


async def _h_skills_run(args: SkillsRunInput, ctx: ToolContext) -> dict[str, Any]:
    name = _validate_entry_name(args.name)
    state = ctx.state
    if state.agent_loop is None:
        raise ToolError("agent loop unavailable")
    try:
        state.agent_loop.get_entry(name)
    except KeyError as exc:
        raise ToolError(f"entry {name!r} not found") from exc
    if name in state.runtime_config.disabled_entries:
        raise ToolError(f"entry {name!r} is disabled")
    body = args.input or {}
    result = await state.agent_loop.run_entry_direct(name, body)
    return {"name": name, "result": result}


# ---------------------------------------------------------------------------
# plugins.list
# ---------------------------------------------------------------------------
class PluginsListInput(BaseModel):
    pass


class PluginsListOutput(_PermissiveModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


async def _h_plugins_list(args: PluginsListInput, ctx: ToolContext) -> dict[str, Any]:
    state = ctx.state
    registry = await state.plugin_loader.load_all()
    configured = state.credential_store.list_services()
    disabled = state.runtime_config.disabled_entries
    items = [
        _meta_to_dict(meta, state.danger_map, configured, disabled) for meta in registry.values()
    ]
    return {"items": items}


# ---------------------------------------------------------------------------
# plugins.install  (mutating — audit_event; uv pip subprocess)
# ---------------------------------------------------------------------------
class PluginsInstallInput(BaseModel):
    name: str


class PluginsInstallOutput(_PermissiveModel):
    name: str
    installed: bool
    reason: str | None = None
    requirements: str | None = None


async def _h_plugins_install(args: PluginsInstallInput, ctx: ToolContext) -> dict[str, Any]:
    name = _validate_entry_name(args.name)
    settings = ctx.state.settings
    plugin_dir: Path = settings.plugins_dir / name
    if not plugin_dir.is_dir():
        raise ToolError(f"plugin directory not found for {name!r}")
    req_file = plugin_dir / "requirements.txt"
    if not req_file.exists():
        return {"name": name, "installed": False, "reason": "no requirements.txt"}

    cmd = ["uv", "pip", "install", "-r", str(req_file)]
    logger.info("bsage_plugins_install", name=name)

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    result = await asyncio.to_thread(_run)
    if result.returncode != 0:
        raise ToolError(f"dependency install failed for {name!r}")
    return {"name": name, "installed": True, "requirements": str(req_file)}


# ---------------------------------------------------------------------------
# plugins.enable / disable  (mutating — audit_event)
# ---------------------------------------------------------------------------
class PluginsToggleInput(BaseModel):
    name: str


class PluginsToggleOutput(_PermissiveModel):
    name: str
    enabled: bool
    changed: bool


async def _toggle(name: str, want_enabled: bool, ctx: ToolContext) -> dict[str, Any]:
    rc = ctx.state.runtime_config
    disabled = list(rc.disabled_entries)
    currently_enabled = name not in disabled
    if currently_enabled == want_enabled:
        return {"name": name, "enabled": want_enabled, "changed": False}
    if want_enabled:
        disabled.remove(name)
    else:
        disabled.append(name)
    rc.update(disabled_entries=disabled)
    agent_loop = getattr(ctx.state, "agent_loop", None)
    if agent_loop is not None:
        try:
            rc.rebuild_enabled(agent_loop._registry, ctx.state.credential_store)
        except Exception:  # noqa: BLE001 — rebuild is best-effort
            logger.warning("bsage_plugins_toggle_rebuild_failed", name=name)
    return {"name": name, "enabled": want_enabled, "changed": True}


async def _h_plugins_enable(args: PluginsToggleInput, ctx: ToolContext) -> dict[str, Any]:
    return await _toggle(_validate_entry_name(args.name), True, ctx)


async def _h_plugins_disable(args: PluginsToggleInput, ctx: ToolContext) -> dict[str, Any]:
    return await _toggle(_validate_entry_name(args.name), False, ctx)


# ---------------------------------------------------------------------------
# garden.list
# ---------------------------------------------------------------------------
class GardenListInput(BaseModel):
    pass


class GardenEntry(BaseModel):
    path: str
    dirs: list[str]
    files: list[str]


class GardenListOutput(_PermissiveModel):
    items: list[GardenEntry] = Field(default_factory=list)


async def _h_garden_list(args: GardenListInput, ctx: ToolContext) -> dict[str, Any]:
    vault_root: Path = ctx.state.vault.root

    def _walk() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for dirpath, dirnames, filenames in os.walk(vault_root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            rel = os.path.relpath(dirpath, vault_root)
            if rel == ".":
                rel = ""
            files = sorted(f for f in filenames if f.endswith(".md"))
            result.append({"path": rel, "dirs": list(dirnames), "files": files})
        return result

    items = await asyncio.to_thread(_walk)
    return {"items": items}


# ---------------------------------------------------------------------------
# canon.list
# ---------------------------------------------------------------------------
class CanonListInput(BaseModel):
    kind: Literal["concepts", "proposals", "actions", "policies"] = "concepts"


class CanonListOutput(_PermissiveModel):
    kind: str
    items: list[Any] = Field(default_factory=list)


async def _h_canon_list(args: CanonListInput, ctx: ToolContext) -> dict[str, Any]:
    index = ctx.state.canon_index
    if args.kind == "concepts":
        items = await index.list_active_concepts()
    elif args.kind == "proposals":
        items = await index.list_proposals()
    elif args.kind == "actions":
        items = await index.list_actions()
    else:
        items = await index.list_policies()
    return {"kind": args.kind, "items": list(items)}


# ---------------------------------------------------------------------------
# canon.draft  (mutating — audit_event)
# ---------------------------------------------------------------------------
class CanonDraftInput(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    slug: str | None = None
    source_proposal: str | None = None


class CanonDraftOutput(_PermissiveModel):
    status: str
    path: str


async def _h_canon_draft(args: CanonDraftInput, ctx: ToolContext) -> dict[str, Any]:
    path = await ctx.state.canon_service.create_action_draft(
        kind=args.kind,
        params=args.params,
        slug=args.slug,
        source_proposal=args.source_proposal,
    )
    return {"status": "draft", "path": path}


# ---------------------------------------------------------------------------
# canon.apply  (mutating — audit_event)
# ---------------------------------------------------------------------------
class CanonApplyInput(BaseModel):
    action_path: str
    mode: Literal["apply", "approve", "reject"] = "apply"
    reason: str | None = None


class CanonApplyOutput(_PermissiveModel):
    action_path: str | None = None
    final_status: str | None = None
    affected_paths: list[str] = Field(default_factory=list)
    error: str | None = None


def _result_to_dict(result: Any, action_path: str, fallback_status: str) -> dict[str, Any]:
    if result is None:
        return {
            "action_path": action_path,
            "final_status": fallback_status,
            "affected_paths": [],
            "error": None,
        }
    return {
        "action_path": getattr(result, "action_path", action_path),
        "final_status": getattr(result, "final_status", fallback_status),
        "affected_paths": list(getattr(result, "affected_paths", []) or []),
        "error": getattr(result, "error", None),
    }


async def _h_canon_apply(args: CanonApplyInput, ctx: ToolContext) -> dict[str, Any]:
    svc = ctx.state.canon_service
    if args.mode == "apply":
        result = await svc.apply_action(args.action_path)
        return _result_to_dict(result, args.action_path, "applied")
    if args.mode == "approve":
        result = await svc.approve_action(args.action_path)
        return _result_to_dict(result, args.action_path, "approved")
    # reject
    result = await svc.reject_action(args.action_path, reason=args.reason)
    return _result_to_dict(result, args.action_path, "rejected")


# ---------------------------------------------------------------------------
# canon.status
# ---------------------------------------------------------------------------
class CanonStatusInput(BaseModel):
    path: str | None = None


class CanonStatusOutput(_PermissiveModel):
    pass


async def _h_canon_status(args: CanonStatusInput, ctx: ToolContext) -> dict[str, Any]:
    if args.path is not None:
        content = await ctx.state._canon_storage.read(args.path)
        return {"path": args.path, "content": content}
    items = await ctx.state.canon_index.list_actions()
    return {"items": list(items)}


# ---------------------------------------------------------------------------
# settings.get
# ---------------------------------------------------------------------------
class SettingsGetInput(BaseModel):
    pass


class SettingsGetOutput(_PermissiveModel):
    settings: dict[str, Any]


async def _h_settings_get(args: SettingsGetInput, ctx: ToolContext) -> dict[str, Any]:
    return {"settings": _settings_snapshot(ctx.state)}


# ---------------------------------------------------------------------------
# settings.set  (mutating — audit_event; secret values never logged)
# ---------------------------------------------------------------------------
class SettingsSetInput(BaseModel):
    key: str
    value: Any = None

    @field_validator("key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        if v not in _VALID_SET_KEYS:
            raise ValueError(
                f"unknown config key: {v!r} (valid: {sorted(_VALID_SET_KEYS)})",
            )
        return v


class SettingsSetOutput(_PermissiveModel):
    settings: dict[str, Any]


async def _h_settings_set(args: SettingsSetInput, ctx: ToolContext) -> dict[str, Any]:
    try:
        update = ConfigUpdate(**{args.key: args.value})
    except Exception as exc:  # noqa: BLE001 — surface as user-facing error
        raise ToolError(f"invalid value for {args.key!r}: {exc}") from exc

    changes = {field: getattr(update, field) for field in update.model_fields_set}
    # Never log the value — secret keys (llm_api_key / embedding_api_key)
    # would otherwise leak into structlog. Log only the field name.
    logger.info("bsage_settings_set", key=args.key)
    try:
        ctx.state.runtime_config.update(**changes)
    except ValueError as exc:
        raise ToolError(f"runtime config update failed: {exc}") from exc

    return {"settings": _settings_snapshot(ctx.state)}


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
_ADMIN_TOOLS: list[Tool] = [
    Tool(
        name="bsage_canon_apply",
        description=(
            "Apply / approve / reject a canonicalization action (mode: apply|approve|reject)."
        ),
        input_schema=CanonApplyInput,
        output_schema=CanonApplyOutput,
        handler=_h_canon_apply,
        required_permission="bsage.canonicalization.apply",
        audit_event="bsage.mcp.canon_apply.invoked",
    ),
    Tool(
        name="bsage_canon_draft",
        description=(
            "Draft a canonicalization action (kind, params, optional slug + source proposal)."
        ),
        input_schema=CanonDraftInput,
        output_schema=CanonDraftOutput,
        handler=_h_canon_draft,
        required_permission="bsage.canonicalization.draft",
        audit_event="bsage.mcp.canon_draft.invoked",
    ),
    Tool(
        name="bsage_canon_list",
        description=(
            "List canonicalization entries by kind: "
            "concepts (default), proposals, actions, policies."
        ),
        input_schema=CanonListInput,
        output_schema=CanonListOutput,
        handler=_h_canon_list,
        required_permission="bsage.canonicalization.read",
    ),
    Tool(
        name="bsage_canon_status",
        description="Show canonicalization status — note when path is set, action list otherwise.",
        input_schema=CanonStatusInput,
        output_schema=CanonStatusOutput,
        handler=_h_canon_status,
        required_permission="bsage.canonicalization.read",
    ),
    Tool(
        name="bsage_garden_list",
        description=(
            "List the vault tree (paths, directories, .md files). "
            "Mutation ops are git-only by design."
        ),
        input_schema=GardenListInput,
        output_schema=GardenListOutput,
        handler=_h_garden_list,
        required_permission="bsage.vault.read",
    ),
    Tool(
        name="bsage_plugins_disable",
        description="Idempotently disable a plugin or skill by name.",
        input_schema=PluginsToggleInput,
        output_schema=PluginsToggleOutput,
        handler=_h_plugins_disable,
        required_permission="bsage.config.write",
        audit_event="bsage.mcp.plugins_disable.invoked",
    ),
    Tool(
        name="bsage_plugins_enable",
        description="Idempotently enable a plugin or skill by name.",
        input_schema=PluginsToggleInput,
        output_schema=PluginsToggleOutput,
        handler=_h_plugins_enable,
        required_permission="bsage.config.write",
        audit_event="bsage.mcp.plugins_enable.invoked",
    ),
    Tool(
        name="bsage_plugins_install",
        description="Install a plugin's dependencies (uv pip install -r requirements.txt).",
        input_schema=PluginsInstallInput,
        output_schema=PluginsInstallOutput,
        handler=_h_plugins_install,
        required_permission="bsage.plugins.install",
        audit_event="bsage.mcp.plugins_install.invoked",
    ),
    Tool(
        name="bsage_plugins_list",
        description="List all loaded plugins (code-based entries).",
        input_schema=PluginsListInput,
        output_schema=PluginsListOutput,
        handler=_h_plugins_list,
        required_permission="bsage.plugins.read",
    ),
    Tool(
        name="bsage_settings_get",
        description=(
            "Read the runtime config snapshot (api keys are reported as has_* booleans only)."
        ),
        input_schema=SettingsGetInput,
        output_schema=SettingsGetOutput,
        handler=_h_settings_get,
        required_permission="bsage.config.read",
    ),
    Tool(
        name="bsage_settings_set",
        description="Update a single runtime config field by key. Validated against ConfigUpdate.",
        input_schema=SettingsSetInput,
        output_schema=SettingsSetOutput,
        handler=_h_settings_set,
        required_permission="bsage.config.write",
        audit_event="bsage.mcp.settings_set.invoked",
    ),
    Tool(
        name="bsage_skills_list",
        description="List all loaded skills (LLM-based entries).",
        input_schema=SkillsListInput,
        output_schema=SkillsListOutput,
        handler=_h_skills_list,
        required_permission="bsage.plugins.read",
    ),
    Tool(
        name="bsage_skills_run",
        description="Run a skill directly with the given input as context.input_data.",
        input_schema=SkillsRunInput,
        output_schema=SkillsRunOutput,
        handler=_h_skills_run,
        required_permission="bsage.plugins.execute",
        audit_event="bsage.mcp.skills_run.invoked",
    ),
]


ADMIN_TOOL_NAMES: list[str] = sorted(t.name for t in _ADMIN_TOOLS)


def register_admin_tools(registry: ToolRegistry) -> None:
    """Register every admin tool into ``registry``."""
    for tool in _ADMIN_TOOLS:
        registry.register(tool)


__all__ = [
    "ADMIN_TOOL_NAMES",
    "register_admin_tools",
]
