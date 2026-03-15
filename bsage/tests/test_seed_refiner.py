"""Tests for AgentLoop._refine_seed() — seed data refinement via LLM."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.agent_loop import AgentLoop


def _build_agent_loop(llm_response: str | Exception = "{}") -> AgentLoop:
    """Build an AgentLoop with all dependencies mocked."""
    registry: dict[str, Any] = {}
    runner = MagicMock()
    safe_mode_guard = MagicMock()
    garden_writer = MagicMock()

    llm_client = MagicMock()
    if isinstance(llm_response, Exception):
        llm_client.chat = AsyncMock(side_effect=llm_response)
    else:
        llm_client.chat = AsyncMock(return_value=llm_response)

    return AgentLoop(
        registry=registry,
        runner=runner,
        safe_mode_guard=safe_mode_guard,
        garden_writer=garden_writer,
        llm_client=llm_client,
    )


@pytest.mark.asyncio()
async def test_structured_data_passed_through() -> None:
    """Data that already has title + content should skip LLM refinement."""
    loop = _build_agent_loop()
    raw = {"title": "My Title", "content": "Some content here"}

    result = await loop._refine_seed("test-plugin", raw)

    assert result == raw
    loop._llm_client.chat.assert_not_called()


@pytest.mark.asyncio()
async def test_short_data_passed_through() -> None:
    """Data shorter than 20 chars when serialized should skip LLM refinement."""
    loop = _build_agent_loop()
    raw = {"x": "y"}

    result = await loop._refine_seed("test-plugin", raw)

    assert result == raw
    loop._llm_client.chat.assert_not_called()


@pytest.mark.asyncio()
async def test_llm_refines_unstructured_data() -> None:
    """Unstructured data should be sent to LLM and parsed back."""
    refined = {"title": "Refined Title", "content": "Refined content", "tags": ["a"]}
    loop = _build_agent_loop(llm_response=json.dumps(refined))
    raw = {"message": "This is a long enough unstructured message for refinement"}

    result = await loop._refine_seed("test-plugin", raw)

    assert result == refined
    loop._llm_client.chat.assert_called_once()


@pytest.mark.asyncio()
async def test_llm_failure_falls_back_to_raw() -> None:
    """When LLM raises an exception, raw_data is returned unchanged."""
    loop = _build_agent_loop(llm_response=RuntimeError("LLM unavailable"))
    raw = {"message": "This is a long enough unstructured message for fallback test"}

    result = await loop._refine_seed("test-plugin", raw)

    assert result == raw


@pytest.mark.asyncio()
async def test_llm_invalid_json_falls_back_to_raw() -> None:
    """When LLM returns non-JSON text, raw_data is returned."""
    loop = _build_agent_loop(llm_response="not valid json at all")
    raw = {"message": "This is a long enough unstructured message for json test"}

    result = await loop._refine_seed("test-plugin", raw)

    assert result == raw


@pytest.mark.asyncio()
async def test_llm_returns_json_without_title_falls_back() -> None:
    """When LLM returns valid JSON but missing title, raw_data is returned."""
    loop = _build_agent_loop(llm_response=json.dumps({"content": "no title here"}))
    raw = {"message": "This is a long enough unstructured message for missing-title test"}

    result = await loop._refine_seed("test-plugin", raw)

    assert result == raw


@pytest.mark.asyncio()
async def test_llm_called_with_system_prompt_and_raw_text() -> None:
    """Verify the LLM is called with the correct system prompt and serialized data."""
    refined = {"title": "T", "content": "C", "tags": []}
    loop = _build_agent_loop(llm_response=json.dumps(refined))
    raw = {"data": "enough characters to pass the length check easily here"}

    await loop._refine_seed("test-plugin", raw)

    call_kwargs = loop._llm_client.chat.call_args
    assert call_kwargs.kwargs.get("system") or call_kwargs.args[0]  # system prompt provided
    messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[1]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    # The user message should contain the serialized raw data
    assert "enough characters" in messages[0]["content"]
