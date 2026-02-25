"""Tests for bsage.core.llm — LiteLLMClient."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bsage.core.llm import LiteLLMClient
from bsage.core.runtime_config import RuntimeConfig


def _make_config(**overrides) -> RuntimeConfig:
    defaults = {
        "llm_model": "anthropic/claude-sonnet-4-20250514",
        "llm_api_key": "",
        "llm_api_base": None,
        "safe_mode": True,
    }
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


class TestLiteLLMClient:
    """Test LiteLLMClient wrapper around litellm.acompletion."""

    @patch("bsage.core.llm.litellm")
    async def test_chat_calls_acompletion(self, mock_litellm) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from LLM"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        config = _make_config(llm_api_key="test-key")
        client = LiteLLMClient(runtime_config=config)
        result = await client.chat(
            system="You are a helpful assistant",
            messages=[{"role": "user", "content": "Hi"}],
        )

        assert result == "Hello from LLM"
        mock_litellm.acompletion.assert_called_once()
        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["model"] == "anthropic/claude-sonnet-4-20250514"
        assert call_kwargs.kwargs["api_key"] == "test-key"

    @patch("bsage.core.llm.litellm")
    async def test_chat_includes_system_message(self, mock_litellm) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        config = _make_config(llm_model="ollama/llama3")
        client = LiteLLMClient(runtime_config=config)
        await client.chat(
            system="Be concise",
            messages=[{"role": "user", "content": "Hello"}],
        )

        call_kwargs = mock_litellm.acompletion.call_args
        messages = call_kwargs.kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "Be concise"}
        assert messages[1] == {"role": "user", "content": "Hello"}

    @patch("bsage.core.llm.litellm")
    async def test_chat_passes_api_base(self, mock_litellm) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "OK"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        config = _make_config(
            llm_model="ollama/llama3",
            llm_api_base="http://localhost:11434",
        )
        client = LiteLLMClient(runtime_config=config)
        await client.chat(system="test", messages=[])

        call_kwargs = mock_litellm.acompletion.call_args
        assert call_kwargs.kwargs["api_base"] == "http://localhost:11434"

    @patch("bsage.core.llm.litellm")
    async def test_chat_omits_empty_api_key(self, mock_litellm) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "OK"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        config = _make_config(llm_model="ollama/llama3", llm_api_key="")
        client = LiteLLMClient(runtime_config=config)
        await client.chat(system="test", messages=[])

        call_kwargs = mock_litellm.acompletion.call_args
        assert "api_key" not in call_kwargs.kwargs

    @patch("bsage.core.llm.litellm")
    async def test_chat_raises_on_error(self, mock_litellm) -> None:
        mock_litellm.acompletion = AsyncMock(side_effect=Exception("API error"))

        config = _make_config(llm_api_key="test")
        client = LiteLLMClient(runtime_config=config)
        with pytest.raises(Exception, match="API error"):
            await client.chat(system="test", messages=[])

    @patch("bsage.core.llm.litellm")
    async def test_chat_raises_on_empty_choices(self, mock_litellm) -> None:
        mock_response = MagicMock()
        mock_response.choices = []
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        config = _make_config(llm_api_key="test")
        client = LiteLLMClient(runtime_config=config)
        with pytest.raises(RuntimeError, match="empty choices"):
            await client.chat(system="test", messages=[])

    @patch("bsage.core.llm.litellm")
    async def test_chat_reflects_runtime_config_change(self, mock_litellm) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "OK"
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        config = _make_config(llm_model="model-a")
        client = LiteLLMClient(runtime_config=config)

        await client.chat(system="test", messages=[])
        call1 = mock_litellm.acompletion.call_args
        assert call1.kwargs["model"] == "model-a"

        # Change model at runtime
        config.update(llm_model="model-b")
        await client.chat(system="test", messages=[])
        call2 = mock_litellm.acompletion.call_args
        assert call2.kwargs["model"] == "model-b"


def _make_text_response(text: str) -> MagicMock:
    """Create a mock LLM response with plain text (no tool calls)."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    resp.choices[0].message.tool_calls = None
    resp.choices[0].message.model_dump.return_value = {
        "role": "assistant",
        "content": text,
    }
    return resp


def _make_tool_call_response(tool_call_id: str, name: str, args: dict) -> MagicMock:
    """Create a mock LLM response with a tool call."""
    tc = MagicMock()
    tc.id = tool_call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)

    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = None
    resp.choices[0].message.tool_calls = [tc]
    resp.choices[0].message.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }
    return resp


class TestChatWithTools:
    """Test LiteLLMClient.chat with tools (tool use loop)."""

    @patch("bsage.core.llm.litellm")
    async def test_no_tool_calls_returns_text(self, mock_litellm) -> None:
        mock_litellm.acompletion = AsyncMock(return_value=_make_text_response("Plain answer"))

        config = _make_config(llm_api_key="test")
        client = LiteLLMClient(runtime_config=config)
        handler = AsyncMock(return_value='{"ok": true}')

        tools = [{"type": "function", "function": {"name": "test-tool"}}]
        result = await client.chat(system="sys", messages=[], tools=tools, tool_handler=handler)

        assert result == "Plain answer"
        handler.assert_not_called()

    @patch("bsage.core.llm.litellm")
    async def test_tool_call_executes_handler(self, mock_litellm) -> None:
        mock_litellm.acompletion = AsyncMock(
            side_effect=[
                _make_tool_call_response("tc1", "garden-writer", {"items": []}),
                _make_text_response("Done! Note saved."),
            ]
        )

        config = _make_config(llm_api_key="test")
        client = LiteLLMClient(runtime_config=config)
        handler = AsyncMock(return_value='{"status": "ok"}')

        tools = [{"type": "function", "function": {"name": "garden-writer"}}]
        result = await client.chat(system="sys", messages=[], tools=tools, tool_handler=handler)

        assert result == "Done! Note saved."
        handler.assert_called_once_with("tc1", "garden-writer", {"items": []})

    @patch("bsage.core.llm.litellm")
    async def test_tool_result_appended_to_messages(self, mock_litellm) -> None:
        mock_litellm.acompletion = AsyncMock(
            side_effect=[
                _make_tool_call_response("tc1", "my-skill", {"x": 1}),
                _make_text_response("Final"),
            ]
        )

        config = _make_config(llm_api_key="test")
        client = LiteLLMClient(runtime_config=config)
        handler = AsyncMock(return_value='{"result": 42}')

        result = await client.chat(
            system="sys",
            messages=[{"role": "user", "content": "go"}],
            tools=[{"type": "function", "function": {"name": "my-skill"}}],
            tool_handler=handler,
        )

        assert result == "Final"
        # Second acompletion call should include tool result
        second_call_msgs = mock_litellm.acompletion.call_args_list[1].kwargs["messages"]
        tool_msg = [m for m in second_call_msgs if isinstance(m, dict) and m.get("role") == "tool"]
        assert len(tool_msg) == 1
        assert tool_msg[0]["tool_call_id"] == "tc1"
        assert tool_msg[0]["content"] == '{"result": 42}'

    @patch("bsage.core.llm.litellm")
    async def test_max_rounds_returns_last_content(self, mock_litellm) -> None:
        # Always return tool calls, never text
        mock_litellm.acompletion = AsyncMock(
            return_value=_make_tool_call_response("tc1", "loop-skill", {})
        )

        config = _make_config(llm_api_key="test")
        client = LiteLLMClient(runtime_config=config)
        handler = AsyncMock(return_value="{}")

        result = await client.chat(
            system="sys",
            messages=[],
            tools=[{"type": "function", "function": {"name": "loop-skill"}}],
            tool_handler=handler,
            max_rounds=3,
        )

        assert result == ""
        assert handler.call_count == 3

    @patch("bsage.core.llm.litellm")
    async def test_passes_tools_to_acompletion(self, mock_litellm) -> None:
        mock_litellm.acompletion = AsyncMock(return_value=_make_text_response("ok"))

        config = _make_config(llm_api_key="test")
        client = LiteLLMClient(runtime_config=config)
        tools = [{"type": "function", "function": {"name": "t1", "parameters": {}}}]

        await client.chat(
            system="sys",
            messages=[],
            tools=tools,
            tool_handler=AsyncMock(),
        )

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["tools"] == tools

