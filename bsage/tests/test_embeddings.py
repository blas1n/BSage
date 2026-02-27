"""Tests for bsage.garden.embeddings — EmbeddingClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bsage.garden.embeddings import EmbeddingClient


def _make_runtime_config(**overrides):
    """Create a mock RuntimeConfig with embedding fields."""
    defaults = {
        "embedding_model": "text-embedding-3-small",
        "embedding_api_key": "emb-key",
        "embedding_api_base": None,
        "llm_api_key": "llm-key",
        "llm_api_base": None,
    }
    defaults.update(overrides)
    config = MagicMock()
    for k, v in defaults.items():
        setattr(config, k, v)
    return config


def _mock_response(embeddings: list[list[float]]):
    resp = MagicMock()
    resp.data = [{"embedding": emb} for emb in embeddings]
    return resp


class TestEmbedClient:
    """Test EmbeddingClient.embed()."""

    async def test_embed_calls_litellm(self) -> None:
        config = _make_runtime_config()
        client = EmbeddingClient(config)

        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aemb:
            mock_aemb.return_value = _mock_response([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
            result = await client.embed(["hello", "world"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_aemb.assert_called_once()
        call_kwargs = mock_aemb.call_args.kwargs
        assert call_kwargs["model"] == "text-embedding-3-small"
        assert call_kwargs["input"] == ["hello", "world"]
        assert call_kwargs["api_key"] == "emb-key"

    async def test_embed_falls_back_to_llm_key(self) -> None:
        config = _make_runtime_config(embedding_api_key="", embedding_api_base=None)
        client = EmbeddingClient(config)

        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aemb:
            mock_aemb.return_value = _mock_response([[0.1]])
            await client.embed(["test"])

        call_kwargs = mock_aemb.call_args.kwargs
        assert call_kwargs["api_key"] == "llm-key"

    async def test_embed_no_model_raises(self) -> None:
        config = _make_runtime_config(embedding_model="")
        client = EmbeddingClient(config)

        with pytest.raises(RuntimeError, match="not configured"):
            await client.embed(["test"])

    async def test_embed_with_api_base(self) -> None:
        config = _make_runtime_config(embedding_api_base="http://localhost:11434")
        client = EmbeddingClient(config)

        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aemb:
            mock_aemb.return_value = _mock_response([[0.1]])
            await client.embed(["test"])

        call_kwargs = mock_aemb.call_args.kwargs
        assert call_kwargs["api_base"] == "http://localhost:11434"

    async def test_embed_no_api_key_omitted(self) -> None:
        config = _make_runtime_config(embedding_api_key="", llm_api_key="")
        client = EmbeddingClient(config)

        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aemb:
            mock_aemb.return_value = _mock_response([[0.1]])
            await client.embed(["test"])

        call_kwargs = mock_aemb.call_args.kwargs
        assert "api_key" not in call_kwargs


class TestEmbedOne:
    """Test EmbeddingClient.embed_one() convenience method."""

    async def test_embed_one_returns_single_vector(self) -> None:
        config = _make_runtime_config()
        client = EmbeddingClient(config)

        with patch("litellm.aembedding", new_callable=AsyncMock) as mock_aemb:
            mock_aemb.return_value = _mock_response([[0.1, 0.2, 0.3]])
            result = await client.embed_one("hello")

        assert result == [0.1, 0.2, 0.3]
