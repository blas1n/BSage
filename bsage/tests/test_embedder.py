"""Tests for Embedder — litellm embedding wrapper."""

from unittest.mock import MagicMock, patch

import pytest

from bsage.garden.embedder import Embedder


class TestEmbedder:
    def test_enabled_when_model_set(self) -> None:
        e = Embedder(model="text-embedding-3-small")
        assert e.enabled is True

    def test_disabled_when_model_empty(self) -> None:
        e = Embedder(model="")
        assert e.enabled is False

    @patch("litellm.aembedding")
    async def test_embed_calls_litellm(self, mock_aembedding) -> None:
        mock_response = MagicMock()
        mock_response.data = [{"embedding": [0.1, 0.2, 0.3]}]
        mock_aembedding.return_value = mock_response

        e = Embedder(model="text-embedding-3-small", api_key="test-key")
        result = await e.embed("Hello world")

        assert result == [0.1, 0.2, 0.3]
        mock_aembedding.assert_awaited_once_with(
            model="text-embedding-3-small",
            input=["Hello world"],
            api_key="test-key",
        )

    @patch("litellm.aembedding")
    async def test_embed_with_api_base(self, mock_aembedding) -> None:
        mock_response = MagicMock()
        mock_response.data = [{"embedding": [0.5]}]
        mock_aembedding.return_value = mock_response

        e = Embedder(
            model="ollama/nomic-embed-text",
            api_base="http://localhost:11434",
        )
        await e.embed("test")

        call_kwargs = mock_aembedding.call_args.kwargs
        assert call_kwargs["api_base"] == "http://localhost:11434"

    @patch("litellm.aembedding")
    async def test_embed_many(self, mock_aembedding) -> None:
        mock_response = MagicMock()
        mock_response.data = [
            {"index": 1, "embedding": [0.4, 0.5]},
            {"index": 0, "embedding": [0.1, 0.2]},
        ]
        mock_aembedding.return_value = mock_response

        e = Embedder(model="text-embedding-3-small")
        results = await e.embed_many(["first", "second"])

        assert len(results) == 2
        assert results[0] == [0.1, 0.2]  # index 0
        assert results[1] == [0.4, 0.5]  # index 1

    async def test_embed_many_empty(self) -> None:
        e = Embedder(model="text-embedding-3-small")
        results = await e.embed_many([])
        assert results == []

    @patch("litellm.aembedding")
    async def test_embed_raises_runtime_error_on_failure(self, mock_aembedding) -> None:
        mock_aembedding.side_effect = Exception("API timeout")
        e = Embedder(model="text-embedding-3-small")
        with pytest.raises(RuntimeError, match="Embedding call failed"):
            await e.embed("test")

    @patch("litellm.aembedding")
    async def test_embed_many_raises_runtime_error_on_failure(self, mock_aembedding) -> None:
        mock_aembedding.side_effect = Exception("rate limit")
        e = Embedder(model="text-embedding-3-small")
        with pytest.raises(RuntimeError, match="Embedding batch call failed"):
            await e.embed_many(["a", "b"])
