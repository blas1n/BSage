"""Tests for bsage.core.agent_loop — AgentLoop orchestration via trigger matching."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.agent_loop import AgentLoop
from bsage.core.skill_loader import SkillMeta


def _make_meta(**overrides) -> SkillMeta:
    defaults = {
        "name": "test-skill",
        "version": "1.0.0",
        "category": "process",
        "is_dangerous": False,
        "description": "Test skill",
    }
    defaults.update(overrides)
    return SkillMeta(**defaults)


@pytest.fixture()
def mock_deps():
    """Create all mocked dependencies for AgentLoop."""
    registry = {
        "calendar-input": _make_meta(
            name="calendar-input",
            category="input",
            trigger={"type": "cron", "schedule": "*/15 * * * *"},
        ),
        "garden-writer": _make_meta(
            name="garden-writer",
            category="process",
            trigger={"type": "on_input"},
        ),
        "insight-linker": _make_meta(
            name="insight-linker",
            category="process",
            trigger={"type": "on_input", "sources": ["calendar-input"]},
        ),
        "dangerous-skill": _make_meta(
            name="dangerous-skill",
            category="process",
            is_dangerous=True,
            trigger={"type": "on_input"},
        ),
        "skill-builder": _make_meta(
            name="skill-builder",
            category="process",
            trigger={"type": "on_demand", "hint": "When a new skill is needed"},
        ),
    }
    skill_runner = MagicMock()
    skill_runner.run = AsyncMock(return_value={"status": "ok"})
    safe_mode_guard = MagicMock()
    safe_mode_guard.check = AsyncMock(return_value=True)
    garden_writer = MagicMock()
    garden_writer.write_seed = AsyncMock()
    garden_writer.write_action = AsyncMock()
    llm_client = MagicMock()
    llm_client.chat = AsyncMock(return_value="none")
    return {
        "registry": registry,
        "skill_runner": skill_runner,
        "safe_mode_guard": safe_mode_guard,
        "garden_writer": garden_writer,
        "llm_client": llm_client,
    }


def _make_loop(deps: dict) -> AgentLoop:
    return AgentLoop(
        registry=deps["registry"],
        skill_runner=deps["skill_runner"],
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

    async def test_on_input_triggers_matching_process_skills(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        await loop.on_input("calendar-input", {"events": [1]})
        # garden-writer (on_input, no sources filter) + insight-linker (sources: [calendar-input])
        # + dangerous-skill (on_input, no sources filter) = 3 triggered
        run_calls = mock_deps["skill_runner"].run.call_args_list
        run_names = [call.args[0].name for call in run_calls]
        assert "garden-writer" in run_names
        assert "insight-linker" in run_names
        assert "dangerous-skill" in run_names

    async def test_on_input_respects_sources_filter(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        # Input from unknown-input — insight-linker should NOT trigger (sources: [calendar-input])
        mock_deps["registry"]["unknown-input"] = _make_meta(name="unknown-input", category="input")
        await loop.on_input("unknown-input", {"data": "test"})
        run_calls = mock_deps["skill_runner"].run.call_args_list
        run_names = [call.args[0].name for call in run_calls]
        assert "garden-writer" in run_names
        assert "insight-linker" not in run_names

    async def test_writes_action_after_skill_run(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        await loop.on_input("calendar-input", {"events": [1]})
        assert mock_deps["garden_writer"].write_action.call_count > 0

    async def test_safe_mode_blocks_dangerous_skill(self, mock_deps) -> None:
        mock_deps["safe_mode_guard"].check = AsyncMock(side_effect=lambda m: not m.is_dangerous)
        loop = _make_loop(mock_deps)
        await loop.on_input("calendar-input", {"events": []})
        run_calls = mock_deps["skill_runner"].run.call_args_list
        run_names = [call.args[0].name for call in run_calls]
        assert "dangerous-skill" not in run_names


class TestAgentLoopFindTriggered:
    """Test _find_triggered_skills logic."""

    async def test_finds_on_input_skills(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        triggered = loop._find_triggered_skills("calendar-input")
        names = [m.name for m in triggered]
        assert "garden-writer" in names
        assert "insight-linker" in names

    async def test_excludes_non_process_skills(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        triggered = loop._find_triggered_skills("calendar-input")
        names = [m.name for m in triggered]
        assert "calendar-input" not in names  # input category

    async def test_excludes_cron_and_on_demand_skills(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        triggered = loop._find_triggered_skills("calendar-input")
        names = [m.name for m in triggered]
        assert "skill-builder" not in names  # on_demand

    async def test_sources_filter_excludes_unmatched(self, mock_deps) -> None:
        loop = _make_loop(mock_deps)
        triggered = loop._find_triggered_skills("unknown-source")
        names = [m.name for m in triggered]
        assert "insight-linker" not in names  # sources: [calendar-input]
        assert "garden-writer" in names  # no sources filter


class TestAgentLoopOnDemand:
    """Test LLM-based on_demand skill selection."""

    async def test_llm_selects_on_demand_skill(self, mock_deps) -> None:
        mock_deps["llm_client"].chat = AsyncMock(return_value="skill-builder")
        loop = _make_loop(mock_deps)
        on_demand = await loop._decide_on_demand_skills("calendar-input", {"data": "test"})
        assert len(on_demand) == 1
        assert on_demand[0].name == "skill-builder"

    async def test_llm_returns_none_no_skills(self, mock_deps) -> None:
        mock_deps["llm_client"].chat = AsyncMock(return_value="none")
        loop = _make_loop(mock_deps)
        on_demand = await loop._decide_on_demand_skills("calendar-input", {"data": "test"})
        assert len(on_demand) == 0

    async def test_llm_ignores_unknown_skill_names(self, mock_deps) -> None:
        mock_deps["llm_client"].chat = AsyncMock(return_value="nonexistent-skill")
        loop = _make_loop(mock_deps)
        on_demand = await loop._decide_on_demand_skills("calendar-input", {"data": "test"})
        assert len(on_demand) == 0

    async def test_no_on_demand_skills_skips_llm(self, mock_deps) -> None:
        # Remove the only on_demand skill
        del mock_deps["registry"]["skill-builder"]
        loop = _make_loop(mock_deps)
        on_demand = await loop._decide_on_demand_skills("calendar-input", {"data": "test"})
        assert len(on_demand) == 0
        mock_deps["llm_client"].chat.assert_not_called()

    async def test_triggerless_process_treated_as_on_demand(self, mock_deps) -> None:
        """Process skills with no trigger are treated as on_demand."""
        mock_deps["registry"]["auto-tagger"] = _make_meta(
            name="auto-tagger",
            category="process",
            trigger=None,  # no trigger = on_demand
        )
        mock_deps["llm_client"].chat = AsyncMock(return_value="auto-tagger")
        loop = _make_loop(mock_deps)
        on_demand = await loop._decide_on_demand_skills("calendar-input", {"data": "test"})
        names = [m.name for m in on_demand]
        assert "auto-tagger" in names


class TestAgentLoopBuildContext:
    """Test _build_context creates proper SkillContext."""

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
