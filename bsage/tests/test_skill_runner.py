"""Tests for bsage.core.skill_runner — Skill execution dispatch."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.exceptions import ConnectorNotFoundError, SkillRunError
from bsage.core.skill_loader import SkillMeta
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
    ctx.connector = MagicMock(return_value=AsyncMock())
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


class TestSkillRunnerConnectorCheck:
    """Test connector requirement validation."""

    async def test_requires_connector_available(self, tmp_path, mock_context) -> None:
        meta = _make_meta(
            name="cal-skill",
            requires_connector="google-calendar",
            entrypoint=None,
        )
        mock_context.connector = AsyncMock(return_value=MagicMock())
        runner = SkillRunner(skills_dir=tmp_path)
        result = await runner.run(meta, mock_context)
        assert "llm_response" in result

    async def test_requires_connector_missing_raises(self, tmp_path, mock_context) -> None:
        meta = _make_meta(
            name="cal-skill",
            requires_connector="google-calendar",
            entrypoint=None,
        )
        mock_context.connector = AsyncMock(side_effect=ConnectorNotFoundError("not connected"))
        runner = SkillRunner(skills_dir=tmp_path)
        with pytest.raises(SkillRunError, match="requires connector"):
            await runner.run(meta, mock_context)


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
