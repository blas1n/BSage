"""Tests for bsage.core.skill_context — SkillContext and ConnectorAccessor."""

from unittest.mock import AsyncMock, MagicMock

from bsage.core.skill_context import ConnectorAccessor, SkillContext


class TestConnectorAccessor:
    """Test ConnectorAccessor callable wrapper."""

    async def test_accessor_calls_manager_get(self) -> None:
        mock_manager = MagicMock()
        mock_connector = MagicMock()
        mock_manager.get = AsyncMock(return_value=mock_connector)

        accessor = ConnectorAccessor(mock_manager)
        result = await accessor("google-calendar")

        mock_manager.get.assert_called_once_with("google-calendar")
        assert result is mock_connector

    async def test_accessor_propagates_error(self) -> None:
        import pytest

        from bsage.core.exceptions import ConnectorNotFoundError

        mock_manager = MagicMock()
        mock_manager.get = AsyncMock(side_effect=ConnectorNotFoundError("not found"))

        accessor = ConnectorAccessor(mock_manager)
        with pytest.raises(ConnectorNotFoundError):
            await accessor("missing")


class TestSkillContext:
    """Test SkillContext dataclass."""

    def test_context_creation(self) -> None:
        context = SkillContext(
            connector=MagicMock(),
            garden=MagicMock(),
            llm=MagicMock(),
            config={"key": "value"},
            logger=MagicMock(),
        )
        assert context.config == {"key": "value"}
        assert context.input_data is None

    def test_context_with_input_data(self) -> None:
        context = SkillContext(
            connector=MagicMock(),
            garden=MagicMock(),
            llm=MagicMock(),
            config={},
            logger=MagicMock(),
            input_data={"events": [1, 2, 3]},
        )
        assert context.input_data == {"events": [1, 2, 3]}
