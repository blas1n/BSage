"""Tests for chat → garden promotion via IngestCompiler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bsage.core.prompt_registry import PromptRegistry
from bsage.gateway.chat import handle_chat


@pytest.fixture()
def prompt_registry(tmp_path: Path) -> PromptRegistry:
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "system.yaml").write_text("template: |\n  You are BSage.\n")
    (d / "chat.yaml").write_text("template: |\n  {context_section}\n")
    return PromptRegistry(d)


def _make_writer() -> AsyncMock:
    writer = AsyncMock()
    writer.read_notes = AsyncMock(return_value=[])
    writer.write_action = AsyncMock()
    writer.write_seed = AsyncMock()
    return writer


def _make_agent_loop(response: str = "Here is my answer.") -> AsyncMock:
    loop = AsyncMock()
    loop.chat = AsyncMock(return_value=response)
    return loop


class TestChatPromotion:
    """Test that handle_chat calls IngestCompiler to promote Q&A."""

    @pytest.mark.asyncio
    async def test_ingest_compiler_called_after_chat(self, prompt_registry: PromptRegistry) -> None:
        """When ingest_compiler is provided, it should be called after chat."""
        writer = _make_writer()
        agent_loop = _make_agent_loop("Knowledge about neural networks.")
        mock_compiler = AsyncMock()
        mock_compiler.compile = AsyncMock()

        await handle_chat(
            message="Tell me about neural networks",
            history=[],
            agent_loop=agent_loop,
            garden_writer=writer,
            prompt_registry=prompt_registry,
            ingest_compiler=mock_compiler,
        )

        mock_compiler.compile.assert_awaited_once()
        call_kwargs = mock_compiler.compile.call_args
        # seed_content should contain both Q and A
        assert "neural networks" in call_kwargs.kwargs.get(
            "seed_content", call_kwargs.args[0] if call_kwargs.args else ""
        )
        assert "Knowledge about" in call_kwargs.kwargs.get(
            "seed_content", call_kwargs.args[0] if call_kwargs.args else ""
        )

    @pytest.mark.asyncio
    async def test_no_compiler_still_works(self, prompt_registry: PromptRegistry) -> None:
        """When ingest_compiler is None, chat should still work normally."""
        writer = _make_writer()
        agent_loop = _make_agent_loop("Response")

        result = await handle_chat(
            message="Hello",
            history=[],
            agent_loop=agent_loop,
            garden_writer=writer,
            prompt_registry=prompt_registry,
            ingest_compiler=None,
        )

        assert result == "Response"
        writer.write_seed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_compiler_source_is_chat(self, prompt_registry: PromptRegistry) -> None:
        """IngestCompiler should receive 'chat' as the seed_source."""
        writer = _make_writer()
        agent_loop = _make_agent_loop("Answer")
        mock_compiler = AsyncMock()
        mock_compiler.compile = AsyncMock()

        await handle_chat(
            message="Question",
            history=[],
            agent_loop=agent_loop,
            garden_writer=writer,
            prompt_registry=prompt_registry,
            ingest_compiler=mock_compiler,
        )

        call_kwargs = mock_compiler.compile.call_args
        fallback = call_kwargs.args[1] if len(call_kwargs.args) > 1 else ""
        source = call_kwargs.kwargs.get("seed_source", fallback)
        assert source == "chat"
