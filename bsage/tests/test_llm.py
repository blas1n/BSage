"""Tests for bsage.core.llm — LiteLLMClient on top of bsvibe_llm.LlmClient.

Mock target: ``bsage.core.llm.LlmClient`` (the bsvibe-llm wrapper). We
verify (a) BSage forwards model / api_key / api_base / tools correctly,
(b) the tool-use loop semantics still hold, and (c) ``suppress_reasoning``
is plumbed through to the underlying complete() call.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bsvibe_llm.client import CompletionResult

from bsage.core.llm import LiteLLMClient
from bsage.core.runtime_config import RuntimeConfig


def _make_config(**overrides) -> RuntimeConfig:
    defaults = {
        "llm_model": "anthropic/claude-sonnet-4-20250514",
        "llm_api_key": "",
        "llm_api_base": None,
        "bsgateway_url": "",
        "safe_mode": True,
    }
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


def _completion_with_text(text: str) -> CompletionResult:
    """Build a CompletionResult whose .raw exposes a plain-text assistant message."""
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None
    msg.model_dump.return_value = {"role": "assistant", "content": text}
    raw = MagicMock()
    raw.choices = [MagicMock(message=msg)]
    return CompletionResult(
        text=text, model="m", finish_reason="stop", prompt_tokens=0, completion_tokens=0, raw=raw
    )


def _completion_with_tool_call(tool_call_id: str, name: str, args: dict) -> CompletionResult:
    """Build a CompletionResult whose .raw carries one tool_call and no content."""
    tc = MagicMock()
    tc.id = tool_call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)

    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]
    msg.model_dump.return_value = {
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
    raw = MagicMock()
    raw.choices = [MagicMock(message=msg)]
    return CompletionResult(
        text="",
        model="m",
        finish_reason="tool_calls",
        prompt_tokens=0,
        completion_tokens=0,
        raw=raw,
    )


@pytest.fixture
def mock_llm_client():
    """Patch the LlmClient class so each LiteLLMClient instantiation gets our mock."""
    with patch("bsage.core.llm.LlmClient") as mock_class:
        instance = MagicMock()
        instance.complete = AsyncMock()
        mock_class.return_value = instance
        yield instance


def _last_complete_kwargs(mock_client: Any) -> dict[str, Any]:
    return mock_client.complete.call_args.kwargs


class TestLiteLLMClient:
    async def test_chat_calls_complete_with_model_and_api_key(self, mock_llm_client) -> None:
        mock_llm_client.complete.return_value = _completion_with_text("Hello from LLM")

        config = _make_config(llm_api_key="test-key")
        client = LiteLLMClient(runtime_config=config)
        result = await client.chat(
            system="You are a helpful assistant",
            messages=[{"role": "user", "content": "Hi"}],
        )

        assert result == "Hello from LLM"
        mock_llm_client.complete.assert_called_once()
        kwargs = _last_complete_kwargs(mock_llm_client)
        # api_key flows through extra (bsvibe-llm doesn't model it on settings)
        assert (kwargs.get("extra") or {}).get("api_key") == "test-key"
        # System message is prepended.
        msgs = kwargs["messages"]
        assert msgs[0] == {"role": "system", "content": "You are a helpful assistant"}
        assert msgs[1] == {"role": "user", "content": "Hi"}

    async def test_chat_passes_api_base_via_extra(self, mock_llm_client) -> None:
        mock_llm_client.complete.return_value = _completion_with_text("OK")

        config = _make_config(
            llm_model="ollama/llama3",
            llm_api_base="http://localhost:11434",
        )
        client = LiteLLMClient(runtime_config=config)
        await client.chat(system="test", messages=[])

        kwargs = _last_complete_kwargs(mock_llm_client)
        assert kwargs["extra"]["api_base"] == "http://localhost:11434"

    async def test_chat_omits_empty_api_key(self, mock_llm_client) -> None:
        mock_llm_client.complete.return_value = _completion_with_text("OK")

        config = _make_config(llm_model="ollama/llama3", llm_api_key="")
        client = LiteLLMClient(runtime_config=config)
        await client.chat(system="test", messages=[])

        kwargs = _last_complete_kwargs(mock_llm_client)
        # No api_key in extra when empty (and extra may itself be None).
        extra = kwargs.get("extra") or {}
        assert "api_key" not in extra

    async def test_chat_uses_direct_mode_when_no_gateway(self, mock_llm_client) -> None:
        mock_llm_client.complete.return_value = _completion_with_text("OK")

        config = _make_config(bsgateway_url="")
        client = LiteLLMClient(runtime_config=config)
        await client.chat(system="t", messages=[])

        kwargs = _last_complete_kwargs(mock_llm_client)
        assert kwargs["direct"] is True

    async def test_chat_uses_gateway_mode_when_configured(self, mock_llm_client) -> None:
        mock_llm_client.complete.return_value = _completion_with_text("OK")

        config = _make_config(bsgateway_url="http://gateway.local:9090")
        client = LiteLLMClient(runtime_config=config)
        await client.chat(system="t", messages=[])

        kwargs = _last_complete_kwargs(mock_llm_client)
        assert kwargs["direct"] is False

    async def test_chat_raises_on_empty_choices(self, mock_llm_client) -> None:
        broken = CompletionResult(
            text="",
            model="m",
            finish_reason="stop",
            prompt_tokens=0,
            completion_tokens=0,
            raw=MagicMock(choices=[]),
        )
        mock_llm_client.complete.return_value = broken

        config = _make_config(llm_api_key="test")
        client = LiteLLMClient(runtime_config=config)
        with pytest.raises(RuntimeError, match="empty choices"):
            await client.chat(system="test", messages=[])

    async def test_chat_reflects_runtime_config_change(self, mock_llm_client) -> None:
        mock_llm_client.complete.return_value = _completion_with_text("OK")

        config = _make_config(llm_model="model-a")
        client = LiteLLMClient(runtime_config=config)

        await client.chat(system="t", messages=[])
        # Settings are rebuilt per call, so a runtime model change takes
        # effect on the very next call (verified via the LlmClient ctor
        # being invoked again with the new model).
        with patch("bsage.core.llm.LlmClient") as mock_class2:
            instance = MagicMock()
            instance.complete = AsyncMock(return_value=_completion_with_text("OK"))
            mock_class2.return_value = instance
            config.update(llm_model="model-b")
            await client.chat(system="t", messages=[])
            # LlmClient was constructed with the new model on the second call.
            settings = mock_class2.call_args.kwargs["settings"]
            assert settings.model == "model-b"


class TestSuppressReasoning:
    async def test_default_does_not_suppress(self, mock_llm_client) -> None:
        mock_llm_client.complete.return_value = _completion_with_text("hi")

        client = LiteLLMClient(runtime_config=_make_config(llm_api_key="k"))
        await client.chat(system="t", messages=[])

        kwargs = _last_complete_kwargs(mock_llm_client)
        assert kwargs["suppress_reasoning"] is False

    async def test_explicit_suppress_forwarded(self, mock_llm_client) -> None:
        mock_llm_client.complete.return_value = _completion_with_text("hi")

        client = LiteLLMClient(runtime_config=_make_config(llm_api_key="k"))
        await client.chat(system="t", messages=[], suppress_reasoning=True)

        kwargs = _last_complete_kwargs(mock_llm_client)
        assert kwargs["suppress_reasoning"] is True

    async def test_suppress_forwarded_in_tool_loop(self, mock_llm_client) -> None:
        # First call returns a tool call; second returns final text.
        mock_llm_client.complete.side_effect = [
            _completion_with_tool_call("tc1", "skill-x", {}),
            _completion_with_text("done"),
        ]

        client = LiteLLMClient(runtime_config=_make_config(llm_api_key="k"))
        handler = AsyncMock(return_value="{}")
        await client.chat(
            system="t",
            messages=[],
            tools=[{"type": "function", "function": {"name": "skill-x"}}],
            tool_handler=handler,
            suppress_reasoning=True,
        )

        # Both round-trips carry the suppression flag.
        for call in mock_llm_client.complete.call_args_list:
            assert call.kwargs["suppress_reasoning"] is True


class TestChatWithTools:
    async def test_no_tool_calls_returns_text(self, mock_llm_client) -> None:
        mock_llm_client.complete.return_value = _completion_with_text("Plain answer")

        client = LiteLLMClient(runtime_config=_make_config(llm_api_key="k"))
        handler = AsyncMock(return_value='{"ok": true}')

        tools = [{"type": "function", "function": {"name": "test-tool"}}]
        result = await client.chat(system="sys", messages=[], tools=tools, tool_handler=handler)

        assert result == "Plain answer"
        handler.assert_not_called()

    async def test_tool_call_executes_handler(self, mock_llm_client) -> None:
        mock_llm_client.complete.side_effect = [
            _completion_with_tool_call("tc1", "garden-writer", {"items": []}),
            _completion_with_text("Done! Note saved."),
        ]

        client = LiteLLMClient(runtime_config=_make_config(llm_api_key="k"))
        handler = AsyncMock(return_value='{"status": "ok"}')

        tools = [{"type": "function", "function": {"name": "garden-writer"}}]
        result = await client.chat(system="sys", messages=[], tools=tools, tool_handler=handler)

        assert result == "Done! Note saved."
        handler.assert_called_once_with("tc1", "garden-writer", {"items": []})

    async def test_tool_result_appended_to_messages(self, mock_llm_client) -> None:
        mock_llm_client.complete.side_effect = [
            _completion_with_tool_call("tc1", "my-skill", {"x": 1}),
            _completion_with_text("Final"),
        ]

        client = LiteLLMClient(runtime_config=_make_config(llm_api_key="k"))
        handler = AsyncMock(return_value='{"result": 42}')

        result = await client.chat(
            system="sys",
            messages=[{"role": "user", "content": "go"}],
            tools=[{"type": "function", "function": {"name": "my-skill"}}],
            tool_handler=handler,
        )

        assert result == "Final"
        # Second complete call should include the tool result message.
        second_msgs = mock_llm_client.complete.call_args_list[1].kwargs["messages"]
        tool_msg = [m for m in second_msgs if isinstance(m, dict) and m.get("role") == "tool"]
        assert len(tool_msg) == 1
        assert tool_msg[0]["tool_call_id"] == "tc1"
        assert tool_msg[0]["content"] == '{"result": 42}'

    async def test_max_rounds_returns_last_content(self, mock_llm_client) -> None:
        # Always return a tool call — never finalize.
        mock_llm_client.complete.return_value = _completion_with_tool_call("tc1", "loop-skill", {})

        client = LiteLLMClient(runtime_config=_make_config(llm_api_key="k"))
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

    async def test_passes_tools_to_complete(self, mock_llm_client) -> None:
        mock_llm_client.complete.return_value = _completion_with_text("ok")

        client = LiteLLMClient(runtime_config=_make_config(llm_api_key="k"))
        tools = [{"type": "function", "function": {"name": "t1", "parameters": {}}}]

        await client.chat(
            system="sys",
            messages=[],
            tools=tools,
            tool_handler=AsyncMock(),
        )

        kwargs = _last_complete_kwargs(mock_llm_client)
        assert kwargs["tools"] == tools
