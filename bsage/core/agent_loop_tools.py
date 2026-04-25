"""Tool-call dispatch helpers for :class:`bsage.core.agent_loop.AgentLoop`.

Pulled out of ``agent_loop.py`` (M15, Hardening Sprint 2). The helpers in
this module are pure functions / dataclasses that translate between the
plugin/skill registry and the OpenAI tool-call surface — this lets the
dispatch logic be tested without spinning up the full agent loop.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

from bsage.garden.writer_tools import (
    APPEND_NOTE_TOOL,
    DELETE_NOTE_TOOL,
    SEARCH_VAULT_TOOL,
    UPDATE_NOTE_TOOL,
    WRITE_NOTE_TOOL,
    WRITE_SEED_TOOL,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from bsage.core.plugin_loader import PluginMeta
    from bsage.core.skill_loader import SkillMeta

logger = structlog.get_logger(__name__)


BUILTIN_TOOLS: tuple[dict[str, Any], ...] = (
    WRITE_NOTE_TOOL,
    WRITE_SEED_TOOL,
    UPDATE_NOTE_TOOL,
    APPEND_NOTE_TOOL,
    DELETE_NOTE_TOOL,
    SEARCH_VAULT_TOOL,
)
"""Built-in vault tools always exposed to the LLM regardless of registry."""


def plugin_tool_definition(meta: PluginMeta) -> dict[str, Any]:
    """Build an OpenAI-format tool definition for a plugin with ``input_schema``."""
    return {
        "type": "function",
        "function": {
            "name": meta.name,
            "description": meta.description,
            "parameters": meta.input_schema,
        },
    }


def build_tools(
    registry: dict[str, PluginMeta | SkillMeta],
    *,
    enabled: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Build OpenAI-format tool definitions including built-in + plugin tools.

    Only ``process``-category plugins with a non-empty ``input_schema`` are
    eligible. When ``enabled`` is provided, plugin names not in the set are
    filtered out — callers pass ``runtime_config.enabled_entries`` here.
    """
    from bsage.core.plugin_loader import PluginMeta

    enabled_set = set(enabled) if enabled is not None else None
    tools: list[dict[str, Any]] = list(BUILTIN_TOOLS)
    for meta in registry.values():
        if not isinstance(meta, PluginMeta):
            continue
        if meta.category != "process" or not meta.input_schema:
            continue
        if enabled_set is not None and meta.name not in enabled_set:
            continue
        tools.append(plugin_tool_definition(meta))
    return tools


def truncate_tool_summary(result: Any, *, limit: int = 200) -> str:
    """Stringify a tool result and truncate for action-log storage."""
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    return text[:limit]


def find_triggered(
    registry: dict[str, PluginMeta | SkillMeta],
    source_name: str,
) -> list[PluginMeta | SkillMeta]:
    """Find process entries with ``trigger.type == "on_input"`` matching ``source_name``.

    A trigger without ``sources`` listens to every input plugin; otherwise
    the source name must be in the configured ``sources`` list.
    """
    result: list[PluginMeta | SkillMeta] = []
    for meta in registry.values():
        if meta.category != "process" or not meta.trigger:
            continue
        if meta.trigger.get("type") != "on_input":
            continue
        sources = meta.trigger.get("sources")
        if sources is None or source_name in sources:
            result.append(meta)
    return result


def collect_on_demand(
    registry: dict[str, PluginMeta | SkillMeta],
) -> list[PluginMeta | SkillMeta]:
    """Return process entries that are eligible for on-demand routing.

    An entry qualifies when its trigger is missing entirely or has type
    ``on_demand`` (the deterministic ``on_input`` triggers go through
    :func:`find_triggered` instead).
    """
    return [
        m
        for m in registry.values()
        if m.category == "process" and (not m.trigger or m.trigger.get("type") == "on_demand")
    ]


def on_demand_tool_definitions(
    on_demand: list[PluginMeta | SkillMeta],
) -> list[dict[str, Any]]:
    """Build tool defs for on-demand plugins that expose an ``input_schema``."""
    from bsage.core.plugin_loader import PluginMeta

    return [
        plugin_tool_definition(m) for m in on_demand if isinstance(m, PluginMeta) and m.input_schema
    ]


def build_router_prompt_fallback(descriptions: str) -> str:
    """Build the inline router system prompt when no PromptRegistry is set."""
    return (
        "You are BSage's plugin router. Given input from a plugin, "
        "decide which on-demand process plugin(s) should run.\n"
        f"Available on-demand plugins:\n{descriptions}\n\n"
        "Respond with ONLY the plugin name(s), one per line. "
        "If none are appropriate, respond with 'none'."
    )


def format_on_demand_descriptions(on_demand: list[PluginMeta | SkillMeta]) -> str:
    """Render plugin name + description (+ optional hint) for the router prompt."""
    return "\n".join(
        f"- {m.name}: {m.description}"
        + (f" (hint: {m.trigger['hint']})" if m.trigger and m.trigger.get("hint") else "")
        for m in on_demand
    )


__all__ = [
    "BUILTIN_TOOLS",
    "build_router_prompt_fallback",
    "build_tools",
    "collect_on_demand",
    "find_triggered",
    "format_on_demand_descriptions",
    "on_demand_tool_definitions",
    "plugin_tool_definition",
    "truncate_tool_summary",
]
