"""Tests for bsage.core.llm — LiteLLMClient."""

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
        config.update_llm(model="model-b")
        await client.chat(system="test", messages=[])
        call2 = mock_litellm.acompletion.call_args
        assert call2.kwargs["model"] == "model-b"
