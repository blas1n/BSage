"""Tests for bsage.core.skill_runner — LLM pipeline execution (GATHER → LLM → APPLY)."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bsage.core.exceptions import SkillRunError
from bsage.core.skill_loader import OutputTarget
from bsage.core.skill_runner import SkillRunner
from bsage.tests.conftest import make_skill_meta as _make_meta


class TestSkillRunnerLLM:
    """Test LLM-based skill execution (Markdown skills)."""

    async def test_run_llm_skill(self, mock_context) -> None:
        meta = _make_meta(name="llm-skill")
        runner = SkillRunner()
        result = await runner.run(meta, mock_context)
        assert "llm_response" in result
        mock_context.llm.chat.assert_called_once()

    async def test_run_llm_skill_passes_description(self, mock_context) -> None:
        meta = _make_meta(
            name="digest-skill",
            description="Generate weekly digest",
        )
        runner = SkillRunner()
        await runner.run(meta, mock_context)
        call_kwargs = mock_context.llm.chat.call_args
        system = call_kwargs.kwargs.get("system", "")
        assert "Generate weekly digest" in system

    async def test_run_raises_skill_run_error_on_failure(self, mock_context) -> None:
        mock_context.llm.chat = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        meta = _make_meta(name="failing-skill")
        runner = SkillRunner()
        with pytest.raises(SkillRunError):
            await runner.run(meta, mock_context)


class TestSkillRunnerPipeline:
    """Test the 3-phase GATHER → LLM → APPLY pipeline for Markdown skills."""

    async def test_gather_reads_vault_notes(self, tmp_path, mock_context) -> None:
        """Phase 1: read_context causes vault notes to be gathered."""
        notes_dir = tmp_path / "vault" / "garden" / "idea"
        notes_dir.mkdir(parents=True)
        (notes_dir / "note1.md").write_text("# Note 1\nContent 1")
        (notes_dir / "note2.md").write_text("# Note 2\nContent 2")

        mock_context.garden.read_notes = AsyncMock(
            return_value=[notes_dir / "note1.md", notes_dir / "note2.md"]
        )
        mock_context.garden.read_note_content = AsyncMock(
            side_effect=lambda p: p.read_text(encoding="utf-8")
        )

        meta = _make_meta(
            name="digest-skill",
            read_context=["garden/idea"],
        )
        runner = SkillRunner()
        await runner.run(meta, mock_context)

        mock_context.garden.read_notes.assert_called_once_with("garden/idea")
        # LLM should receive vault context in user message
        call_args = mock_context.llm.chat.call_args
        msgs = call_args.kwargs.get(
            "messages", call_args.args[1] if len(call_args.args) > 1 else []
        )
        user_msg = msgs[0]
        assert "Note 1" in user_msg["content"]

    async def test_system_prompt_override(self, mock_context) -> None:
        """Phase 2: system_prompt overrides default system message."""
        meta = _make_meta(
            name="custom-skill",
            system_prompt="You are a custom analyzer.",
        )
        runner = SkillRunner()
        await runner.run(meta, mock_context)

        call_args = mock_context.llm.chat.call_args
        system = call_args.kwargs.get("system", call_args.args[0] if call_args.args else "")
        assert "You are a custom analyzer." in system
        assert "custom-skill" not in system

    async def test_output_target_garden(self, mock_context) -> None:
        """Phase 3: output_target=garden writes to garden."""
        mock_context.garden.write_garden = AsyncMock(
            return_value=Path("/vault/garden/idea/output.md")
        )

        meta = _make_meta(
            name="writer-skill",
            output_target=OutputTarget.GARDEN,
            output_note_type="insight",
        )
        runner = SkillRunner()
        result = await runner.run(meta, mock_context)

        assert "output_path" in result
        mock_context.garden.write_garden.assert_called_once()
        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert call_arg["note_type"] == "insight"
        assert call_arg["source"] == "writer-skill"

    async def test_output_target_seeds(self, mock_context) -> None:
        """Phase 3: output_target=seeds writes to seeds."""
        mock_context.garden.write_seed = AsyncMock(return_value=Path("/vault/seeds/test.md"))

        meta = _make_meta(
            name="seed-skill",
            output_target=OutputTarget.SEEDS,
        )
        runner = SkillRunner()
        result = await runner.run(meta, mock_context)

        assert "output_path" in result
        mock_context.garden.write_seed.assert_called_once()

    async def test_no_output_target_returns_response(self, mock_context) -> None:
        """No output_target returns llm_response only."""
        meta = _make_meta(name="simple-skill")
        runner = SkillRunner()
        result = await runner.run(meta, mock_context)

        assert result == {"llm_response": "LLM response text"}

    async def test_json_output_format_strips_fence(self, mock_context) -> None:
        """output_format=json strips markdown code fences."""
        mock_context.llm.chat = AsyncMock(return_value='```json\n{"key": "value"}\n```')
        mock_context.garden.write_garden = AsyncMock(return_value=Path("/vault/out.md"))

        meta = _make_meta(
            name="json-skill",
            output_target=OutputTarget.GARDEN,
            output_format="json",
        )
        runner = SkillRunner()
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert '{"key": "value"}' in call_arg["content"]

    async def test_json_format_adds_instruction(self, mock_context) -> None:
        """output_format=json adds JSON instruction to system prompt."""
        meta = _make_meta(
            name="json-skill",
            output_format="json",
        )
        runner = SkillRunner()
        await runner.run(meta, mock_context)

        call_args = mock_context.llm.chat.call_args
        system = call_args.kwargs.get("system", call_args.args[0] if call_args.args else "")
        assert "valid JSON" in system

    async def test_no_read_context_skips_gather(self, mock_context) -> None:
        """No read_context means no vault reads."""
        meta = _make_meta(name="no-gather")
        runner = SkillRunner()
        await runner.run(meta, mock_context)

        mock_context.garden.read_notes.assert_not_called()

    async def test_gather_stops_at_char_limit(self, tmp_path, mock_context) -> None:
        """Outer loop should break when _MAX_CONTEXT_CHARS is reached."""
        big_text = "x" * 60_000  # exceeds _MAX_CONTEXT_CHARS (50_000)
        mock_context.garden.read_notes = AsyncMock(
            return_value=[tmp_path / "note.md"],
        )
        mock_context.garden.read_note_content = AsyncMock(return_value=big_text)

        meta = _make_meta(
            name="gather-limit",
            read_context=["dir1", "dir2"],
        )
        runner = SkillRunner()
        await runner.run(meta, mock_context)

        # dir1 fills the budget; dir2 should NOT be read
        assert mock_context.garden.read_notes.call_count == 1
        mock_context.garden.read_notes.assert_called_once_with("dir1")

    async def test_strip_json_fence_with_space(self, mock_context) -> None:
        """_strip_json_fence handles ``` json (with space) correctly."""
        mock_context.llm.chat = AsyncMock(return_value='``` json\n{"key": "val"}\n```')
        mock_context.garden.write_garden = AsyncMock(return_value=Path("/vault/out.md"))

        meta = _make_meta(
            name="fence-space",
            output_target=OutputTarget.GARDEN,
            output_format="json",
        )
        runner = SkillRunner()
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert '{"key": "val"}' in call_arg["content"]

    async def test_seeds_json_array_wrapped_in_dict(self, mock_context) -> None:
        """json.loads returning a list should be wrapped in a dict."""
        mock_context.llm.chat = AsyncMock(return_value="[1, 2, 3]")
        mock_context.garden.write_seed = AsyncMock(return_value=Path("/vault/seeds/out.md"))

        meta = _make_meta(
            name="array-skill",
            output_target=OutputTarget.SEEDS,
            output_format="json",
        )
        runner = SkillRunner()
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_seed.call_args.args[1]
        assert isinstance(call_arg, dict)
        assert call_arg["content"] == [1, 2, 3]
        assert call_arg["source"] == "array-skill"

    async def test_strip_tilde_fence(self, mock_context) -> None:
        """_strip_json_fence handles ~~~ fences."""
        mock_context.llm.chat = AsyncMock(return_value='~~~json\n{"key": "val"}\n~~~')
        mock_context.garden.write_garden = AsyncMock(return_value=Path("/vault/out.md"))

        meta = _make_meta(
            name="tilde-fence",
            output_target=OutputTarget.GARDEN,
            output_format="json",
        )
        runner = SkillRunner()
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert '{"key": "val"}' in call_arg["content"]

    async def test_strip_fence_with_prose_around(self, mock_context) -> None:
        """_strip_json_fence handles prose before/after the fence."""
        llm_response = 'Here is the JSON output:\n```json\n{"key": "val"}\n```\nI hope this helps!'
        mock_context.llm.chat = AsyncMock(return_value=llm_response)
        mock_context.garden.write_garden = AsyncMock(return_value=Path("/vault/out.md"))

        meta = _make_meta(
            name="prose-fence",
            output_target=OutputTarget.GARDEN,
            output_format="json",
        )
        runner = SkillRunner()
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert call_arg["content"] == '{"key": "val"}'


class TestSkillRunnerEvents:
    """Test EventBus emission from SkillRunner."""

    async def test_emits_start_and_complete_events(self, mock_context) -> None:
        from bsage.core.events import EventBus, EventType

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        meta = _make_meta(name="event-skill")
        runner = SkillRunner(event_bus=event_bus)
        await runner.run(meta, mock_context)

        types = [c.args[0].event_type for c in sub.on_event.call_args_list]
        assert EventType.SKILL_RUN_START in types
        assert EventType.SKILL_GATHER_COMPLETE in types
        assert EventType.SKILL_LLM_RESPONSE in types
        assert EventType.SKILL_APPLY_COMPLETE in types
        assert EventType.SKILL_RUN_COMPLETE in types

    async def test_all_events_share_correlation_id(self, mock_context) -> None:
        from bsage.core.events import EventBus

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        meta = _make_meta(name="corr-test")
        runner = SkillRunner(event_bus=event_bus)
        await runner.run(meta, mock_context)

        ids = {c.args[0].correlation_id for c in sub.on_event.call_args_list}
        assert len(ids) == 1  # all events share the same correlation_id

    async def test_emits_error_event_on_failure(self, mock_context) -> None:
        from bsage.core.events import EventBus, EventType

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        mock_context.llm.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        meta = _make_meta(name="fail-skill")
        runner = SkillRunner(event_bus=event_bus)

        with pytest.raises(SkillRunError):
            await runner.run(meta, mock_context)

        types = [c.args[0].event_type for c in sub.on_event.call_args_list]
        assert EventType.SKILL_RUN_ERROR in types

    async def test_no_events_when_event_bus_is_none(self, mock_context) -> None:
        meta = _make_meta()
        runner = SkillRunner()  # no event_bus
        result = await runner.run(meta, mock_context)
        assert "llm_response" in result
