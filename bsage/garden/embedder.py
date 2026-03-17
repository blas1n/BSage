"""Embedder — async text embedding via litellm.aembedding."""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class Embedder:
    """Thin wrapper around litellm.aembedding for text embedding.

    Supports any provider that litellm supports (OpenAI, Ollama, Cohere, etc.).
    Disabled when ``model`` is empty.
    """

    def __init__(
        self,
        model: str,
        api_key: str = "",
        api_base: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._api_base = api_base

    @property
    def enabled(self) -> bool:
        """True if an embedding model is configured."""
        return bool(self._model)

    async def embed(self, text: str) -> list[float]:
        """Compute an embedding for a single text.

        Args:
            text: Input text to embed.

        Returns:
            Dense vector embedding as a list of floats.

        Raises:
            RuntimeError: If embedding call fails.
        """
        import litellm

        kwargs: dict = {"model": self._model, "input": [text]}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base

        try:
            response = await litellm.aembedding(**kwargs)
        except Exception as exc:
            logger.error("embedding_failed", model=self._model, exc_info=True)
            raise RuntimeError(f"Embedding call failed: {exc}") from exc
        if not response.data:
            raise RuntimeError("Embedding response contains no data")
        return response.data[0]["embedding"]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for multiple texts in a single call.

        Args:
            texts: List of input texts.

        Returns:
            List of embeddings in the same order as input.
        """
        if not texts:
            return []

        import litellm

        kwargs: dict = {"model": self._model, "input": texts}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base

        try:
            response = await litellm.aembedding(**kwargs)
        except Exception as exc:
            logger.error(
                "embedding_batch_failed", model=self._model, count=len(texts), exc_info=True
            )
            raise RuntimeError(f"Embedding batch call failed: {exc}") from exc
        if not response.data:
            raise RuntimeError("Embedding batch response contains no data")
        # Sort by index to preserve order
        sorted_data = sorted(response.data, key=lambda d: d["index"])
        return [d["embedding"] for d in sorted_data]
