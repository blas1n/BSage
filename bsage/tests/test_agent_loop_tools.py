"""Direct unit tests for ``bsage.core.agent_loop_tools`` (M15 split).

These cover the pure helpers that translate plugin/skill registry entries
into OpenAI tool-call definitions, on-demand router prompts, and trigger
matches. Keeping them as functions (no AgentLoop instance needed) makes the
behaviour cheap to lock in.
"""

from __future__ import annotations

from bsage.core.agent_loop_tools import (
    BUILTIN_TOOLS,
    build_router_prompt_fallback,
    build_tools,
    collect_on_demand,
    find_triggered,
    format_on_demand_descriptions,
    on_demand_tool_definitions,
    plugin_tool_definition,
    truncate_tool_summary,
)
from bsage.tests.conftest import make_plugin_meta, make_skill_meta


def _registry() -> dict:
    return {
        "calendar-input": make_plugin_meta(
            name="calendar-input",
            category="input",
            trigger={"type": "cron", "schedule": "*/15 * * * *"},
        ),
        "insight-linker": make_skill_meta(
            name="insight-linker",
            category="process",
            trigger={"type": "on_input", "sources": ["calendar-input"]},
        ),
        "skill-builder": make_skill_meta(
            name="skill-builder",
            category="process",
            trigger={"type": "on_demand", "hint": "When a new skill is needed"},
        ),
        "tool-plugin": make_plugin_meta(
            name="tool-plugin",
            category="process",
            trigger={"type": "on_input"},
            input_schema={"type": "object", "properties": {"items": {"type": "array"}}},
        ),
        "demand-plugin": make_plugin_meta(
            name="demand-plugin",
            category="process",
            trigger={"type": "on_demand"},
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        ),
    }


class TestBuildTools:
    def test_includes_all_builtin_tools_first(self) -> None:
        tools = build_tools(_registry())
        builtin_names = [t["function"]["name"] for t in BUILTIN_TOOLS]
        assert [t["function"]["name"] for t in tools[: len(BUILTIN_TOOLS)]] == builtin_names

    def test_includes_eligible_plugins(self) -> None:
        tools = build_tools(_registry())
        names = {t["function"]["name"] for t in tools}
        # tool-plugin and demand-plugin are process + have input_schema → exposed
        assert "tool-plugin" in names
        assert "demand-plugin" in names
        # skills must NOT be exposed even if they are process
        assert "insight-linker" not in names
        # input plugins are not process → excluded
        assert "calendar-input" not in names

    def test_enabled_filter(self) -> None:
        tools = build_tools(_registry(), enabled={"tool-plugin"})
        names = {t["function"]["name"] for t in tools}
        assert "tool-plugin" in names
        assert "demand-plugin" not in names
        # builtins are always present, never filtered
        for tool in BUILTIN_TOOLS:
            assert tool["function"]["name"] in names

    def test_skips_plugin_without_input_schema(self) -> None:
        registry = {
            "no-schema": make_plugin_meta(
                name="no-schema",
                category="process",
                trigger={"type": "on_demand"},
                input_schema=None,
            ),
        }
        tools = build_tools(registry)
        names = {t["function"]["name"] for t in tools}
        assert "no-schema" not in names


class TestPluginToolDefinition:
    def test_shape(self) -> None:
        meta = make_plugin_meta(
            name="x",
            category="process",
            input_schema={"type": "object", "properties": {"a": {"type": "string"}}},
        )
        meta.description = "describe x"
        tool = plugin_tool_definition(meta)
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "x"
        assert tool["function"]["description"] == "describe x"
        assert tool["function"]["parameters"]["type"] == "object"


class TestFindTriggered:
    def test_matches_listed_source(self) -> None:
        registry = _registry()
        triggered = find_triggered(registry, "calendar-input")
        names = {m.name for m in triggered}
        assert "insight-linker" in names

    def test_skips_unrelated_source(self) -> None:
        registry = _registry()
        triggered = find_triggered(registry, "telegram-input")
        names = {m.name for m in triggered}
        assert "insight-linker" not in names

    def test_unconfigured_sources_listens_to_everything(self) -> None:
        # tool-plugin's trigger has no sources list → matches every input
        triggered = find_triggered(_registry(), "anything")
        names = {m.name for m in triggered}
        assert "tool-plugin" in names

    def test_skips_non_process_categories(self) -> None:
        triggered = find_triggered(_registry(), "calendar-input")
        # input plugins must not be triggered, even if they're in registry
        assert all(m.category == "process" for m in triggered)


class TestCollectOnDemand:
    def test_includes_on_demand_and_no_trigger(self) -> None:
        registry = {
            "with-trigger": make_plugin_meta(
                name="with-trigger",
                category="process",
                trigger={"type": "on_demand"},
            ),
            "no-trigger": make_plugin_meta(
                name="no-trigger",
                category="process",
                trigger=None,
            ),
            "input-trigger": make_plugin_meta(
                name="input-trigger",
                category="process",
                trigger={"type": "on_input"},
            ),
            "input-cat": make_plugin_meta(
                name="input-cat",
                category="input",
                trigger={"type": "cron", "schedule": "*/5 * * * *"},
            ),
        }
        names = {m.name for m in collect_on_demand(registry)}
        assert names == {"with-trigger", "no-trigger"}


class TestOnDemandToolDefinitions:
    def test_only_plugins_with_input_schema(self) -> None:
        on_demand = [
            make_plugin_meta(
                name="ok",
                category="process",
                trigger={"type": "on_demand"},
                input_schema={"type": "object", "properties": {}},
            ),
            make_plugin_meta(
                name="no-schema",
                category="process",
                trigger={"type": "on_demand"},
                input_schema=None,
            ),
            make_skill_meta(name="skill-x", category="process"),
        ]
        tools = on_demand_tool_definitions(on_demand)
        names = {t["function"]["name"] for t in tools}
        assert names == {"ok"}


class TestRouterPrompt:
    def test_format_includes_descriptions_and_hints(self) -> None:
        on_demand = [
            make_plugin_meta(
                name="alpha",
                category="process",
                trigger={"type": "on_demand", "hint": "when alpha"},
            ),
            make_plugin_meta(
                name="beta",
                category="process",
                trigger={"type": "on_demand"},
            ),
        ]
        on_demand[0].description = "alpha desc"
        on_demand[1].description = "beta desc"
        out = format_on_demand_descriptions(on_demand)
        assert "alpha: alpha desc" in out
        assert "(hint: when alpha)" in out
        assert "beta: beta desc" in out
        # No hint marker for beta
        assert "beta desc (hint:" not in out

    def test_fallback_prompt_includes_descriptions(self) -> None:
        prompt = build_router_prompt_fallback("- a: desc\n- b: desc")
        assert "BSage's plugin router" in prompt
        assert "- a: desc" in prompt
        assert "- b: desc" in prompt
        assert "'none'" in prompt


class TestTruncate:
    def test_str_truncated(self) -> None:
        assert truncate_tool_summary("x" * 500, limit=10) == "x" * 10

    def test_dict_serialised_then_truncated(self) -> None:
        out = truncate_tool_summary({"k": "v" * 500}, limit=20)
        assert isinstance(out, str)
        assert len(out) == 20

    def test_default_limit_is_200(self) -> None:
        out = truncate_tool_summary("x" * 1000)
        assert len(out) == 200
