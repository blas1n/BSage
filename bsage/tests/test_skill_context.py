"""Tests for bsage.core.skill_context — SkillContext."""

from unittest.mock import AsyncMock, MagicMock

from bsage.core.skill_context import SkillContext


class TestSkillContext:
    """Test SkillContext dataclass."""

    def test_context_creation(self) -> None:
        context = SkillContext(
            garden=MagicMock(),
            llm=MagicMock(),
            config={"key": "value"},
            logger=MagicMock(),
        )
        assert context.config == {"key": "value"}
        assert context.credentials == {}
        assert context.input_data is None
        assert context.chat is None

    def test_context_with_input_data(self) -> None:
        context = SkillContext(
            garden=MagicMock(),
            llm=MagicMock(),
            config={},
            logger=MagicMock(),
            input_data={"events": [1, 2, 3]},
        )
        assert context.input_data == {"events": [1, 2, 3]}

    def test_context_with_credentials(self) -> None:
        context = SkillContext(
            garden=MagicMock(),
            llm=MagicMock(),
            config={},
            logger=MagicMock(),
            credentials={"api_key": "secret"},
        )
        assert context.credentials == {"api_key": "secret"}

    def test_context_with_chat(self) -> None:
        mock_chat = AsyncMock()
        context = SkillContext(
            garden=MagicMock(),
            llm=MagicMock(),
            config={},
            logger=MagicMock(),
            chat=mock_chat,
        )
        assert context.chat is mock_chat
