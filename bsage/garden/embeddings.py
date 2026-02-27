"""EmbeddingClient — unified embedding interface via litellm.aembedding."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from bsage.core.runtime_config import RuntimeConfig

logger = structlog.get_logger(__name__)


class EmbeddingClient:
    """Async wrapper around ``litellm.aembedding``.

    Reads embedding model config from ``RuntimeConfig`` so it can be changed
    at runtime without restart, mirroring the ``LiteLLMClient`` pattern.
    """

    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self._config = runtime_config

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of text strings.

        Args:
            texts: List of strings to embed.

        Returns:
            List of embedding vectors (same order as input).

        Raises:
            RuntimeError: If embedding model is not configured.
        """
        model = self._config.embedding_model
        if not model:
            raise RuntimeError("Embedding model not configured (EMBEDDING_MODEL env var)")

        import litellm

        api_key = self._config.embedding_api_key or self._config.llm_api_key
        api_base = self._config.embedding_api_base or self._config.llm_api_base

        kwargs: dict[str, Any] = {"model": model, "input": texts}
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        logger.debug("embedding_request", model=model, count=len(texts))
        response = await litellm.aembedding(**kwargs)

        vectors = [item["embedding"] for item in response.data]
        logger.debug(
            "embedding_response",
            model=model,
            dimensions=len(vectors[0]) if vectors else 0,
        )
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        """Embed a single text string. Convenience wrapper."""
        results = await self.embed([text])
        return results[0]
