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

    def test_new_fields_default_to_none(self) -> None:
        context = SkillContext(
            garden=MagicMock(),
            llm=MagicMock(),
            config={},
            logger=MagicMock(),
        )
        assert context.retriever is None
        assert context.scheduler is None
        assert context.events is None

    def test_context_with_retriever(self) -> None:
        mock_retriever = AsyncMock()
        context = SkillContext(
            garden=MagicMock(),
            llm=MagicMock(),
            config={},
            logger=MagicMock(),
            retriever=mock_retriever,
        )
        assert context.retriever is mock_retriever

    def test_context_with_scheduler(self) -> None:
        mock_scheduler = AsyncMock()
        context = SkillContext(
            garden=MagicMock(),
            llm=MagicMock(),
            config={},
            logger=MagicMock(),
            scheduler=mock_scheduler,
        )
        assert context.scheduler is mock_scheduler

    def test_context_with_events(self) -> None:
        mock_events = AsyncMock()
        context = SkillContext(
            garden=MagicMock(),
            llm=MagicMock(),
            config={},
            logger=MagicMock(),
            events=mock_events,
        )
        assert context.events is mock_events


class TestRetrieverAdapter:
    """Test RetrieverAdapter wraps VaultRetriever correctly."""

    async def test_search_delegates_to_retriever(self) -> None:
        from bsage.core.skill_context import RetrieverAdapter

        mock_retriever = AsyncMock()
        mock_retriever.retrieve = AsyncMock(return_value="search results")
        adapter = RetrieverAdapter(mock_retriever)

        result = await adapter.search("test query", context_dirs=["garden/idea"])
        assert result == "search results"
        mock_retriever.retrieve.assert_called_once_with(
            query="test query",
            context_dirs=["garden/idea"],
            max_chars=50_000,
            top_k=20,
        )

    async def test_search_uses_default_dirs(self) -> None:
        from bsage.core.skill_context import RetrieverAdapter

        mock_retriever = AsyncMock()
        mock_retriever.retrieve = AsyncMock(return_value="")
        adapter = RetrieverAdapter(mock_retriever)

        await adapter.search("query")
        call_kwargs = mock_retriever.retrieve.call_args.kwargs
        assert call_kwargs["context_dirs"] == ["seeds", "garden/idea", "garden/insight"]
