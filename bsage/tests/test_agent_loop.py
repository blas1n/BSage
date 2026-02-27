"""Tests for bsage.core.agent_loop — AgentLoop orchestration via trigger matching."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.agent_loop import AgentLoop
from bsage.core.plugin_loader import PluginMeta
from bsage.core.skill_loader import SkillMeta


def _make_plugin_meta(**overrides) -> PluginMeta:
    defaults = {
        "name": "test-plugin",
        "version": "1.0.0",
        "category": "process",
        "description": "Test plugin",
    }
    defaults.update(overrides)
    return PluginMeta(**defaults)


def _make_skill_meta(**overrides) -> SkillMeta:
    defaults = {
        "name": "test-skill",
        "version": "1.0.0",
        "category": "process",
        "description": "Test skill",
    }
    defaults.update(overrides)
    return SkillMeta(**defaults)


@pytest.fixture()
def mock_deps():
    """Create all mocked dependencies for AgentLoop."""
    registry = {
        "calendar-input": _make_plugin_meta(
            name="calendar-input",
            category="input",
            trigger={"type": "cron", "schedule": "*/15 * * * *"},
        ),
        "insight-linker": _make_skill_meta(
            name="insight-linker",
            category="process",
            trigger={"type": "on_input", "sources": ["calendar-input"]},
        ),
        "dangerous-plugin": _make_plugin_meta(
            name="dangerous-plugin",
            category="process",
            trigger={"type": "on_input"},
        ),
        "skill-builder": _make_skill_meta(
            name="skill-builder",
            category="process",
            trigger={"type": "on_demand", "hint": "When a new skill is needed"},
        ),
        "tool-plugin": _make_plugin_meta(
            name="tool-plugin",
            category="process",
            trigger={"type": "on_input"},
            input_schema={"type": "object", "properties": {"items": {"type": "array"}}},
        ),
    }
    runner = MagicMock()
    runner.run = AsyncMock(return_value={"status": "ok"})
    safe_mode_guard = MagicMock()
    safe_mode_guard.check = AsyncMock(return_value=True)
    garden_writer = MagicMock()
    garden_writer.write_seed = AsyncMock()
    garden_writer.write_action = AsyncMock()
    garden_writer.write_from_items = AsyncMock()
    llm_client = MagicMock()
    llm_client.chat = AsyncMock(return_value="none")
    return {
        "registry": registry,
        "runner": runner,
        "safe_mode_guard": safe_mode_guard,
        "garden_writer": garden_writer,
        "llm_client": llm_client,
    }


def _make_loop(deps: dict) -> AgentLoop:
    return AgentLoop(
        registry=deps["registry"],
        runner=deps["runner"],
        safe_mode_guard=deps["safe_mode_guard"],
        garden_writer=deps["garden_writer"],
        llm_client=deps["llm_client"],
    )


class TestAgentLoopOnInput:
    """Test on_input orchestration."""

    async def test_writes_seed_on_input(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        await loop.on_input("calendar-input", {"events": [1, 2]})
        mock_deps["garden_writer"].write_seed.assert_called_once_with(
            "calendar-input", {"events": [1, 2]}
        )

    async def test_write_from_items_called_when_items_present(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        await loop.on_input("calendar-input", {"items": [{"title": "A", "content": "B"}]})
        mock_deps["garden_writer"].write_from_items.assert_called_once_with(
            "calendar-input", [{"title": "A", "content": "B"}]
        )

    async def test_write_from_items_skipped_when_no_items(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        await loop.on_input("calendar-input", {"events": [1, 2]})
        mock_deps["garden_writer"].write_from_items.assert_not_called()

    async def test_on_input_triggers_matching_process_entries(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        await loop.on_input("calendar-input", {"events": [1]})
        run_calls = mock_deps["runner"].run.call_args_list
        run_names = [call.args[0].name for call in run_calls]
        assert "insight-linker" in run_names
        assert "dangerous-plugin" in run_names
        assert "tool-plugin" in run_names

    async def test_on_input_respects_sources_filter(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        mock_deps["registry"]["unknown-input"] = _make_plugin_meta(
            name="unknown-input", category="input"
        )
        await loop.on_input("unknown-input", {"data": "test"})
        run_calls = mock_deps["runner"].run.call_args_list
        run_names = [call.args[0].name for call in run_calls]
        assert "tool-plugin" in run_names
        assert "insight-linker" not in run_names

    async def test_writes_action_after_entry_run(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        await loop.on_input("calendar-input", {"events": [1]})
        assert mock_deps["garden_writer"].write_action.call_count > 0

    async def test_safe_mode_blocks_dangerous_entry(self, mock_deps) -> None:
        _dangerous = {"dangerous-plugin"}
        mock_deps["safe_mode_guard"].check = AsyncMock(
            side_effect=lambda m: m.name not in _dangerous
        )
        loop = _make_loop(mock_deps)
        await loop.on_input("calendar-input", {"events": []})
        run_calls = mock_deps["runner"].run.call_args_list
        run_names = [call.args[0].name for call in run_calls]
        assert "dangerous-plugin" not in run_names


class TestAgentLoopFindTriggered:
    """Test _find_triggered logic."""

    async def test_finds_on_input_entries(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        triggered = loop._find_triggered("calendar-input")
        names = [m.name for m in triggered]
        assert "insight-linker" in names
        assert "tool-plugin" in names

    async def test_excludes_non_process_entries(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        triggered = loop._find_triggered("calendar-input")
        names = [m.name for m in triggered]
        assert "calendar-input" not in names

    async def test_excludes_cron_and_on_demand_entries(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        triggered = loop._find_triggered("calendar-input")
        names = [m.name for m in triggered]
        assert "skill-builder" not in names

    async def test_sources_filter_excludes_unmatched(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        triggered = loop._find_triggered("unknown-source")
        names = [m.name for m in triggered]
        assert "insight-linker" not in names
        assert "tool-plugin" in names


class TestAgentLoopOnDemand:
    """Test LLM-based on_demand routing."""

    async def test_text_routing_selects_and_runs_entry(self, mock_deps) -> None:
        """On-demand entry without input_schema uses text-based routing."""
        mock_deps["llm_client"].chat = AsyncMock(return_value="skill-builder")
        loop = _make_loop(mock_deps)
        results = await loop._decide_on_demand("calendar-input", {"data": "test"})
        assert len(results) == 1
        assert results[0]["status"] == "ok"
        run_calls = mock_deps["runner"].run.call_args_list
        run_names = [call.args[0].name for call in run_calls]
        assert "skill-builder" in run_names

    async def test_text_routing_none_returns_empty(self, mock_deps) -> None:
        mock_deps["llm_client"].chat = AsyncMock(return_value="none")
        loop = _make_loop(mock_deps)
        results = await loop._decide_on_demand("calendar-input", {"data": "test"})
        assert len(results) == 0

    async def test_text_routing_ignores_unknown_names(self, mock_deps) -> None:
        mock_deps["llm_client"].chat = AsyncMock(return_value="nonexistent-plugin")
        loop = _make_loop(mock_deps)
        results = await loop._decide_on_demand("calendar-input", {"data": "test"})
        assert len(results) == 0

    async def test_no_on_demand_entries_skips_llm(self, mock_deps) -> None:
        del mock_deps["registry"]["skill-builder"]
        loop = _make_loop(mock_deps)
        results = await loop._decide_on_demand("calendar-input", {"data": "test"})
        assert len(results) == 0
        mock_deps["llm_client"].chat.assert_not_called()

    async def test_triggerless_process_treated_as_on_demand(self, mock_deps) -> None:
        mock_deps["registry"]["auto-tagger"] = _make_skill_meta(
            name="auto-tagger",
            category="process",
            trigger=None,
        )
        mock_deps["llm_client"].chat = AsyncMock(return_value="auto-tagger")
        loop = _make_loop(mock_deps)
        results = await loop._decide_on_demand("calendar-input", {"data": "test"})
        assert len(results) >= 1

    async def test_tool_use_path_when_plugin_has_input_schema(self, mock_deps) -> None:
        """On-demand plugin with input_schema uses tool use routing."""
        mock_deps["registry"]["schema-plugin"] = _make_plugin_meta(
            name="schema-plugin",
            category="process",
            trigger={"type": "on_demand"},
            input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        mock_deps["llm_client"].chat = AsyncMock(return_value="Done")
        loop = _make_loop(mock_deps)
        await loop._decide_on_demand("test-input", {"data": "test"})
        call_kwargs = mock_deps["llm_client"].chat.call_args.kwargs
        assert call_kwargs["tools"] is not None


class TestAgentLoopChat:
    """Test interactive chat with tool use."""

    async def test_chat_uses_tools_when_available(self, mock_deps) -> None:
        mock_deps["llm_client"].chat = AsyncMock(return_value="Chat response")
        loop = _make_loop(mock_deps)
        result = await loop.chat(
            system="You are BSage",
            messages=[{"role": "user", "content": "Save a note"}],
        )
        assert result == "Chat response"
        call_kwargs = mock_deps["llm_client"].chat.call_args.kwargs
        assert call_kwargs["tools"] is not None

    async def test_chat_always_has_write_note_tool(self, mock_deps) -> None:
        # Even with no plugin input_schema, write-note is always available
        for meta in mock_deps["registry"].values():
            if isinstance(meta, PluginMeta):
                meta.input_schema = None
        mock_deps["llm_client"].chat = AsyncMock(return_value="Response")
        loop = _make_loop(mock_deps)
        result = await loop.chat(
            system="You are BSage",
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert result == "Response"
        call_kwargs = mock_deps["llm_client"].chat.call_args.kwargs
        tool_names = [t["function"]["name"] for t in call_kwargs["tools"]]
        assert "write-note" in tool_names
        assert call_kwargs["tool_handler"] is not None

    async def test_chat_passes_system_and_messages(self, mock_deps) -> None:
        mock_deps["llm_client"].chat = AsyncMock(return_value="ok")
        loop = _make_loop(mock_deps)
        msgs = [{"role": "user", "content": "hi"}]
        await loop.chat(system="sys prompt", messages=msgs)
        call_kwargs = mock_deps["llm_client"].chat.call_args.kwargs
        assert call_kwargs["system"] == "sys prompt"
        assert call_kwargs["messages"] == msgs


class TestBuildTools:
    """Test _build_tools tool definition generation."""

    async def test_always_includes_write_note(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        tools = loop._build_tools()
        tool_names = [t["function"]["name"] for t in tools]
        assert "write-note" in tool_names

    async def test_includes_write_note_even_with_empty_registry(self, mock_deps) -> None:
        mock_deps["registry"] = {}
        loop = _make_loop(mock_deps)
        tools = loop._build_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "write-note"

    async def test_includes_plugins_with_input_schema(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        tools = loop._build_tools()
        tool_names = [t["function"]["name"] for t in tools]
        assert "tool-plugin" in tool_names

    async def test_excludes_skills_even_with_input_schema(self, mock_deps) -> None:
        # SkillMeta has no input_schema — but even if it did, only PluginMeta is included
        loop = _make_loop(mock_deps)
        tools = loop._build_tools()
        tool_names = [t["function"]["name"] for t in tools]
        assert "insight-linker" not in tool_names
        assert "skill-builder" not in tool_names

    async def test_excludes_plugins_without_input_schema(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        tools = loop._build_tools()
        tool_names = [t["function"]["name"] for t in tools]
        assert "calendar-input" not in tool_names

    async def test_tool_format_is_openai_compatible(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        tools = loop._build_tools()
        for tool in tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]


class TestHandleToolCall:
    """Test _handle_tool_call execution."""

    async def test_runs_entry_via_runner(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        result = await loop._handle_tool_call("tc1", "tool-plugin", {"items": []})
        mock_deps["runner"].run.assert_called_once()
        assert "ok" in result

    async def test_unknown_entry_returns_error(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        result = await loop._handle_tool_call("tc1", "nonexistent", {})
        assert "error" in result
        assert "Unknown plugin" in result

    async def test_safe_mode_rejection(self, mock_deps) -> None:
        mock_deps["safe_mode_guard"].check = AsyncMock(return_value=False)
        loop = _make_loop(mock_deps)
        result = await loop._handle_tool_call("tc1", "tool-plugin", {})
        assert "rejected" in result
        mock_deps["runner"].run.assert_not_called()

    async def test_writes_action_on_success(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        await loop._handle_tool_call("tc1", "tool-plugin", {"items": []})
        mock_deps["garden_writer"].write_action.assert_called_once()

    async def test_passes_args_as_input_data(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        await loop._handle_tool_call("tc1", "tool-plugin", {"items": [{"title": "Test"}]})
        context = mock_deps["runner"].run.call_args.args[1]
        assert context.input_data == {"items": [{"title": "Test"}]}

    async def test_write_note_routes_to_garden_writer(self, mock_deps) -> None:
        mock_deps["garden_writer"].handle_write_note = AsyncMock(
            return_value={"status": "saved", "title": "Test", "path": "/vault/test.md"}
        )
        loop = _make_loop(mock_deps)
        result = await loop._handle_tool_call(
            "tc1", "write-note", {"title": "Test", "content": "Body"}
        )
        mock_deps["garden_writer"].handle_write_note.assert_called_once_with(
            {"title": "Test", "content": "Body"}
        )
        assert "saved" in result
        mock_deps["runner"].run.assert_not_called()

    async def test_write_note_logs_action(self, mock_deps) -> None:
        mock_deps["garden_writer"].handle_write_note = AsyncMock(
            return_value={"status": "saved", "title": "T", "path": "/p"}
        )
        loop = _make_loop(mock_deps)
        await loop._handle_tool_call("tc1", "write-note", {"title": "T", "content": "C"})
        mock_deps["garden_writer"].write_action.assert_called_once()
        call_args = mock_deps["garden_writer"].write_action.call_args
        assert call_args.args[0] == "write-note"


class TestAgentLoopBuildContext:
    """Test build_context creates proper SkillContext."""

    async def test_build_context_has_required_fields(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        context = loop.build_context(input_data={"key": "value"})
        assert context.input_data == {"key": "value"}
        assert context.llm is mock_deps["llm_client"]
        assert context.garden is mock_deps["garden_writer"]

    async def test_build_context_none_input_data(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        context = loop.build_context(input_data=None)
        assert context.input_data is None


class TestAgentLoopEvents:
    """Test EventBus emission from AgentLoop."""

    async def test_on_input_emits_start_and_complete(self, mock_deps) -> None:
        from bsage.core.events import EventBus, EventType

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        loop = AgentLoop(
            registry=mock_deps["registry"],
            runner=mock_deps["runner"],
            safe_mode_guard=mock_deps["safe_mode_guard"],
            garden_writer=mock_deps["garden_writer"],
            llm_client=mock_deps["llm_client"],
            event_bus=event_bus,
        )
        await loop.on_input("calendar-input", {"events": []})

        types = [c.args[0].event_type for c in sub.on_event.call_args_list]
        assert EventType.INPUT_RECEIVED in types
        assert EventType.INPUT_COMPLETE in types

    async def test_no_events_when_event_bus_is_none(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)  # no event_bus
        results = await loop.on_input("calendar-input", {"events": []})
        assert isinstance(results, list)
