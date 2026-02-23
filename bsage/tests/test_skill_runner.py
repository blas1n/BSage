"""Tests for bsage.core.skill_runner — Skill execution dispatch."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.credential_store import CredentialStore
from bsage.core.exceptions import CredentialNotFoundError, SkillRunError
from bsage.core.skill_loader import OutputTarget, SkillMeta
from bsage.core.skill_runner import SkillRunner


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
def mock_context():
    ctx = MagicMock()
    ctx.logger = MagicMock()
    ctx.credentials = {}
    ctx.garden = AsyncMock()
    ctx.llm = AsyncMock()
    ctx.llm.chat = AsyncMock(return_value="LLM response text")
    ctx.config = {}
    ctx.input_data = None
    return ctx


@pytest.fixture()
def sample_skill_dir(tmp_path):
    """Create a temporary skills directory with a Python skill."""
    skill_dir = tmp_path / "py-skill"
    skill_dir.mkdir()
    (skill_dir / "skill.yaml").write_text(
        "name: py-skill\nversion: 1.0.0\ncategory: process\n"
        "is_dangerous: false\ndescription: Python test skill\n"
        "entrypoint: skill.py::execute\n"
    )
    (skill_dir / "skill.py").write_text(
        'async def execute(context):\n    return {"status": "ok", "data": "from python"}\n'
    )
    return tmp_path


class TestSkillRunnerPython:
    """Test Python skill execution via importlib."""

    async def test_run_python_skill(self, sample_skill_dir, mock_context) -> None:
        meta = _make_meta(name="py-skill", entrypoint="skill.py::execute")
        runner = SkillRunner(skills_dir=sample_skill_dir)
        result = await runner.run(meta, mock_context)
        assert result["status"] == "ok"
        assert result["data"] == "from python"

    async def test_run_python_skill_missing_module(self, tmp_path, mock_context) -> None:
        skill_dir = tmp_path / "missing-skill"
        skill_dir.mkdir()
        meta = _make_meta(name="missing-skill", entrypoint="skill.py::execute")
        runner = SkillRunner(skills_dir=tmp_path)
        with pytest.raises(SkillRunError):
            await runner.run(meta, mock_context)


class TestSkillRunnerLLM:
    """Test LLM-based skill execution (yaml-only skills)."""

    async def test_run_llm_skill(self, tmp_path, mock_context) -> None:
        meta = _make_meta(name="llm-skill", entrypoint=None)
        runner = SkillRunner(skills_dir=tmp_path)
        result = await runner.run(meta, mock_context)
        assert "llm_response" in result
        mock_context.llm.chat.assert_called_once()

    async def test_run_llm_skill_passes_description(self, tmp_path, mock_context) -> None:
        meta = _make_meta(
            name="digest-skill",
            entrypoint=None,
            description="Generate weekly digest",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)
        call_kwargs = mock_context.llm.chat.call_args
        assert "Generate weekly digest" in call_kwargs.kwargs.get(
            "system", call_kwargs.args[0] if call_kwargs.args else ""
        )


class TestSkillRunnerEdgeCases:
    """Test edge cases and security checks."""

    async def test_malformed_entrypoint_raises(self, tmp_path, mock_context) -> None:
        meta = _make_meta(name="bad-skill", entrypoint="no_separator")
        runner = SkillRunner(skills_dir=tmp_path)
        with pytest.raises(SkillRunError, match="Invalid entrypoint format"):
            await runner.run(meta, mock_context)

    async def test_function_not_found_raises(self, tmp_path, mock_context) -> None:
        skill_dir = tmp_path / "fn-skill"
        skill_dir.mkdir()
        (skill_dir / "skill.py").write_text("async def other():\n    pass\n")
        meta = _make_meta(name="fn-skill", entrypoint="skill.py::execute")
        runner = SkillRunner(skills_dir=tmp_path)
        with pytest.raises(SkillRunError, match="Function 'execute' not found"):
            await runner.run(meta, mock_context)

    async def test_path_traversal_raises(self, tmp_path, mock_context) -> None:
        meta = _make_meta(name="../../etc", entrypoint="passwd::execute")
        runner = SkillRunner(skills_dir=tmp_path)
        with pytest.raises(SkillRunError, match="Path traversal detected"):
            await runner.run(meta, mock_context)


class TestSkillRunnerPipeline:
    """Test the 3-phase GATHER → LLM → APPLY pipeline for yaml-only skills."""

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
            entrypoint=None,
            read_context=["garden/idea"],
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        mock_context.garden.read_notes.assert_called_once_with("garden/idea")
        # LLM should receive vault context in user message
        call_args = mock_context.llm.chat.call_args
        msgs = call_args.kwargs.get(
            "messages", call_args.args[1] if len(call_args.args) > 1 else []
        )
        user_msg = msgs[0]
        assert "Note 1" in user_msg["content"]

    async def test_system_prompt_override(self, tmp_path, mock_context) -> None:
        """Phase 2: system_prompt overrides default system message."""
        meta = _make_meta(
            name="custom-skill",
            entrypoint=None,
            system_prompt="You are a custom analyzer.",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        call_args = mock_context.llm.chat.call_args
        system = call_args.kwargs.get("system", call_args.args[0] if call_args.args else "")
        assert "You are a custom analyzer." in system
        assert "custom-skill" not in system  # default message not present

    async def test_output_target_garden(self, tmp_path, mock_context) -> None:
        """Phase 3: output_target=garden writes to garden."""

        mock_context.garden.write_garden = AsyncMock(
            return_value=Path("/vault/garden/idea/output.md")
        )

        meta = _make_meta(
            name="writer-skill",
            entrypoint=None,
            output_target=OutputTarget.GARDEN,
            output_note_type="insight",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        result = await runner.run(meta, mock_context)

        assert "output_path" in result
        mock_context.garden.write_garden.assert_called_once()
        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert call_arg["note_type"] == "insight"
        assert call_arg["source"] == "writer-skill"

    async def test_output_target_seeds(self, tmp_path, mock_context) -> None:
        """Phase 3: output_target=seeds writes to seeds."""

        mock_context.garden.write_seed = AsyncMock(return_value=Path("/vault/seeds/test.md"))

        meta = _make_meta(
            name="seed-skill",
            entrypoint=None,
            output_target=OutputTarget.SEEDS,
        )
        runner = SkillRunner(skills_dir=tmp_path)
        result = await runner.run(meta, mock_context)

        assert "output_path" in result
        mock_context.garden.write_seed.assert_called_once()

    async def test_no_output_target_returns_response(self, tmp_path, mock_context) -> None:
        """No output_target returns llm_response only."""
        meta = _make_meta(name="simple-skill", entrypoint=None)
        runner = SkillRunner(skills_dir=tmp_path)
        result = await runner.run(meta, mock_context)

        assert result == {"llm_response": "LLM response text"}

    async def test_json_output_format_strips_fence(self, tmp_path, mock_context) -> None:
        """output_format=json strips markdown code fences."""

        mock_context.llm.chat = AsyncMock(return_value='```json\n{"key": "value"}\n```')
        mock_context.garden.write_garden = AsyncMock(return_value=Path("/vault/out.md"))

        meta = _make_meta(
            name="json-skill",
            entrypoint=None,
            output_target=OutputTarget.GARDEN,
            output_format="json",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert '{"key": "value"}' in call_arg["content"]

    async def test_json_format_adds_instruction(self, tmp_path, mock_context) -> None:
        """output_format=json adds JSON instruction to system prompt."""
        meta = _make_meta(
            name="json-skill",
            entrypoint=None,
            output_format="json",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        call_args = mock_context.llm.chat.call_args
        system = call_args.kwargs.get("system", call_args.args[0] if call_args.args else "")
        assert "valid JSON" in system

    async def test_no_read_context_skips_gather(self, tmp_path, mock_context) -> None:
        """No read_context means no vault reads."""
        meta = _make_meta(name="no-gather", entrypoint=None)
        runner = SkillRunner(skills_dir=tmp_path)
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
            entrypoint=None,
            read_context=["dir1", "dir2"],
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        # dir1 fills the budget; dir2 should NOT be read
        assert mock_context.garden.read_notes.call_count == 1
        mock_context.garden.read_notes.assert_called_once_with("dir1")

    async def test_strip_json_fence_with_space(self, tmp_path, mock_context) -> None:
        """_strip_json_fence handles ``` json (with space) correctly."""
        mock_context.llm.chat = AsyncMock(return_value='``` json\n{"key": "val"}\n```')
        mock_context.garden.write_garden = AsyncMock(return_value=Path("/vault/out.md"))

        meta = _make_meta(
            name="fence-space",
            entrypoint=None,
            output_target=OutputTarget.GARDEN,
            output_format="json",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert '{"key": "val"}' in call_arg["content"]

    async def test_seeds_json_array_wrapped_in_dict(self, tmp_path, mock_context) -> None:
        """json.loads returning a list should be wrapped in a dict."""
        mock_context.llm.chat = AsyncMock(return_value="[1, 2, 3]")
        mock_context.garden.write_seed = AsyncMock(return_value=Path("/vault/seeds/out.md"))

        meta = _make_meta(
            name="array-skill",
            entrypoint=None,
            output_target=OutputTarget.SEEDS,
            output_format="json",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_seed.call_args.args[1]
        assert isinstance(call_arg, dict)
        assert call_arg["content"] == [1, 2, 3]
        assert call_arg["source"] == "array-skill"

    async def test_strip_tilde_fence(self, tmp_path, mock_context) -> None:
        """_strip_json_fence handles ~~~ fences."""
        mock_context.llm.chat = AsyncMock(return_value='~~~json\n{"key": "val"}\n~~~')
        mock_context.garden.write_garden = AsyncMock(return_value=Path("/vault/out.md"))

        meta = _make_meta(
            name="tilde-fence",
            entrypoint=None,
            output_target=OutputTarget.GARDEN,
            output_format="json",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert '{"key": "val"}' in call_arg["content"]

    async def test_strip_fence_with_prose_around(self, tmp_path, mock_context) -> None:
        """_strip_json_fence handles prose before/after the fence."""
        llm_response = 'Here is the JSON output:\n```json\n{"key": "val"}\n```\nI hope this helps!'
        mock_context.llm.chat = AsyncMock(return_value=llm_response)
        mock_context.garden.write_garden = AsyncMock(return_value=Path("/vault/out.md"))

        meta = _make_meta(
            name="prose-fence",
            entrypoint=None,
            output_target=OutputTarget.GARDEN,
            output_format="json",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert call_arg["content"] == '{"key": "val"}'

    async def test_strip_fence_with_extended_backticks(self, tmp_path, mock_context) -> None:
        """_strip_json_fence handles ```` (4+ backtick) fences."""
        mock_context.llm.chat = AsyncMock(return_value='````json\n{"key": "val"}\n````')
        mock_context.garden.write_garden = AsyncMock(return_value=Path("/vault/out.md"))

        meta = _make_meta(
            name="long-fence",
            entrypoint=None,
            output_target=OutputTarget.GARDEN,
            output_format="json",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert call_arg["content"] == '{"key": "val"}'

    async def test_strip_fence_no_fence_returns_as_is(self, tmp_path, mock_context) -> None:
        """_strip_json_fence returns raw text when no fence present."""
        mock_context.llm.chat = AsyncMock(return_value='{"key": "val"}')
        mock_context.garden.write_garden = AsyncMock(return_value=Path("/vault/out.md"))

        meta = _make_meta(
            name="no-fence",
            entrypoint=None,
            output_target=OutputTarget.GARDEN,
            output_format="json",
        )
        runner = SkillRunner(skills_dir=tmp_path)
        await runner.run(meta, mock_context)

        call_arg = mock_context.garden.write_garden.call_args.args[0]
        assert call_arg["content"] == '{"key": "val"}'


class TestSkillRunnerCredentials:
    """Test credential auto-injection via CredentialStore."""

    async def test_credentials_injected_when_available(self, sample_skill_dir) -> None:
        ctx = MagicMock()
        ctx.credentials = {}
        ctx.config = {}
        ctx.input_data = None

        cred_store = MagicMock(spec=CredentialStore)
        cred_store.get = AsyncMock(return_value={"api_key": "secret"})

        meta = _make_meta(name="py-skill", entrypoint="skill.py::execute")
        runner = SkillRunner(skills_dir=sample_skill_dir, credential_store=cred_store)
        await runner.run(meta, ctx)
        assert ctx.credentials == {"api_key": "secret"}

    async def test_no_credentials_does_not_fail(self, sample_skill_dir) -> None:
        ctx = MagicMock()
        ctx.credentials = {}
        ctx.config = {}
        ctx.input_data = None

        cred_store = MagicMock(spec=CredentialStore)
        cred_store.get = AsyncMock(side_effect=CredentialNotFoundError("no creds"))

        meta = _make_meta(name="py-skill", entrypoint="skill.py::execute")
        runner = SkillRunner(skills_dir=sample_skill_dir, credential_store=cred_store)
        result = await runner.run(meta, ctx)
        assert result["status"] == "ok"
        assert ctx.credentials == {}

    async def test_no_credential_store_skips_injection(self, sample_skill_dir) -> None:
        ctx = MagicMock()
        ctx.credentials = {}
        ctx.config = {}
        ctx.input_data = None

        meta = _make_meta(name="py-skill", entrypoint="skill.py::execute")
        runner = SkillRunner(skills_dir=sample_skill_dir)
        result = await runner.run(meta, ctx)
        assert result["status"] == "ok"
        assert ctx.credentials == {}


class TestSkillRunnerNotify:
    """Test run_notify for notification entrypoint execution."""

    async def test_run_notify_calls_notification_entrypoint(self, tmp_path, mock_context) -> None:
        skill_dir = tmp_path / "telegram-input"
        skill_dir.mkdir()
        (skill_dir / "skill.py").write_text(
            "async def notify(context):\n"
            '    return {"sent": True, "message": context.input_data["message"]}\n'
        )

        meta = _make_meta(
            name="telegram-input",
            category="input",
            entrypoint="skill.py::execute",
            notification_entrypoint="skill.py::notify",
        )
        mock_context.input_data = {"message": "hello", "level": "info"}
        runner = SkillRunner(skills_dir=tmp_path)
        result = await runner.run_notify(meta, mock_context)
        assert result["sent"] is True

    async def test_run_notify_without_entrypoint_raises(self, tmp_path, mock_context) -> None:
        meta = _make_meta(name="no-notify", notification_entrypoint=None)
        runner = SkillRunner(skills_dir=tmp_path)
        with pytest.raises(SkillRunError, match="no notification_entrypoint"):
            await runner.run_notify(meta, mock_context)

    async def test_run_notify_injects_credentials(self, tmp_path) -> None:
        skill_dir = tmp_path / "tg-input"
        skill_dir.mkdir()
        (skill_dir / "skill.py").write_text(
            "async def notify(context):\n"
            '    return {"token": context.credentials.get("bot_token")}\n'
        )

        ctx = MagicMock()
        ctx.credentials = {}
        ctx.config = {}
        ctx.input_data = {"message": "hi", "level": "info"}

        cred_store = MagicMock(spec=CredentialStore)
        cred_store.get = AsyncMock(return_value={"bot_token": "tok123"})

        meta = _make_meta(
            name="tg-input",
            category="input",
            notification_entrypoint="skill.py::notify",
        )
        runner = SkillRunner(skills_dir=tmp_path, credential_store=cred_store)
        result = await runner.run_notify(meta, ctx)
        assert result["token"] == "tok123"
