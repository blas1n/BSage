"""Tests for ChatBridge — unified chat interface."""

from unittest.mock import AsyncMock, patch

import pytest

from bsage.core.chat_bridge import ChatBridge


@pytest.fixture
def bridge_deps():
    """Common dependencies for ChatBridge."""
    return {
        "agent_loop": AsyncMock(),
        "garden_writer": AsyncMock(),
        "prompt_registry": AsyncMock(),
        "retriever": AsyncMock(),
    }


async def test_chat_calls_handle_chat(bridge_deps) -> None:
    bridge = ChatBridge(**bridge_deps)

    with patch("bsage.gateway.chat.handle_chat", new_callable=AsyncMock) as mock_hc:
        mock_hc.return_value = "Hello from BSage"
        result = await bridge.chat(message="Hi")

    assert result == "Hello from BSage"
    mock_hc.assert_awaited_once_with(
        message="Hi",
        history=[],
        agent_loop=bridge_deps["agent_loop"],
        garden_writer=bridge_deps["garden_writer"],
        prompt_registry=bridge_deps["prompt_registry"],
        context_paths=None,
        retriever=bridge_deps["retriever"],
        ingest_compiler=None,
    )


async def test_chat_with_history_and_context_paths(bridge_deps) -> None:
    bridge = ChatBridge(**bridge_deps)
    history = [{"role": "user", "content": "prev"}]

    with patch("bsage.gateway.chat.handle_chat", new_callable=AsyncMock) as mock_hc:
        mock_hc.return_value = "reply"
        await bridge.chat(message="Hi", history=history, context_paths=["garden/idea"])

    call_kwargs = mock_hc.call_args[1]
    assert call_kwargs["history"] == history
    assert call_kwargs["context_paths"] == ["garden/idea"]


async def test_reply_fn_called_when_set(bridge_deps) -> None:
    reply_fn = AsyncMock()
    bridge = ChatBridge(**bridge_deps, reply_fn=reply_fn)

    with patch("bsage.gateway.chat.handle_chat", new_callable=AsyncMock) as mock_hc:
        mock_hc.return_value = "  Hi there  "
        await bridge.chat(message="Hello")

    reply_fn.assert_awaited_once_with("Hi there")


async def test_reply_fn_not_called_when_none(bridge_deps) -> None:
    bridge = ChatBridge(**bridge_deps, reply_fn=None)

    with patch("bsage.gateway.chat.handle_chat", new_callable=AsyncMock) as mock_hc:
        mock_hc.return_value = "reply"
        result = await bridge.chat(message="Hi")

    assert result == "reply"


async def test_reply_fn_not_called_for_empty_response(bridge_deps) -> None:
    reply_fn = AsyncMock()
    bridge = ChatBridge(**bridge_deps, reply_fn=reply_fn)

    with patch("bsage.gateway.chat.handle_chat", new_callable=AsyncMock) as mock_hc:
        mock_hc.return_value = "   "
        await bridge.chat(message="Hi")

    reply_fn.assert_not_awaited()


async def test_reply_fn_not_called_for_empty_string(bridge_deps) -> None:
    reply_fn = AsyncMock()
    bridge = ChatBridge(**bridge_deps, reply_fn=reply_fn)

    with patch("bsage.gateway.chat.handle_chat", new_callable=AsyncMock) as mock_hc:
        mock_hc.return_value = ""
        await bridge.chat(message="Hi")

    reply_fn.assert_not_awaited()


async def test_reply_fn_failure_does_not_break_chat(bridge_deps) -> None:
    reply_fn = AsyncMock(side_effect=RuntimeError("send failed"))
    bridge = ChatBridge(**bridge_deps, reply_fn=reply_fn)

    with patch("bsage.gateway.chat.handle_chat", new_callable=AsyncMock) as mock_hc:
        mock_hc.return_value = "Hello from BSage"
        result = await bridge.chat(message="Hi")

    assert result == "Hello from BSage"
    reply_fn.assert_awaited_once_with("Hello from BSage")
