"""Direct unit tests for ``bsage.core.agent_loop_seed_refiner`` (M15 split).

The seed-refiner is critical: it sits in the public webhook ingestion path,
so it MUST never bubble exceptions back to callers (Sprint 1 PR #24
guarantee). These tests lock that invariant in at the helper level.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.agent_loop_seed_refiner import (
    REFINE_PROMPT_FALLBACK,
    refine_seed,
    resolve_refine_prompt,
)


class TestResolvePrompt:
    def test_uses_registry_when_available(self) -> None:
        registry = MagicMock()
        registry.get = MagicMock(return_value="custom prompt")
        assert resolve_refine_prompt(registry) == "custom prompt"
        registry.get.assert_called_once_with("seed-refiner")

    def test_falls_back_when_registry_missing_key(self) -> None:
        registry = MagicMock()
        registry.get = MagicMock(side_effect=KeyError("seed-refiner"))
        assert resolve_refine_prompt(registry) == REFINE_PROMPT_FALLBACK

    def test_falls_back_when_no_registry(self) -> None:
        assert resolve_refine_prompt(None) == REFINE_PROMPT_FALLBACK


class TestRefineSeed:
    @pytest.mark.asyncio
    async def test_skips_when_already_structured(self) -> None:
        llm = MagicMock()
        llm.chat = AsyncMock()
        result = await refine_seed(
            plugin_name="x",
            raw_data={"title": "t", "content": "c"},
            llm_client=llm,
            prompt_registry=None,
        )
        assert result == {"title": "t", "content": "c"}
        # LLM must NOT be called when input is already structured
        llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_too_small(self) -> None:
        llm = MagicMock()
        llm.chat = AsyncMock()
        result = await refine_seed(
            plugin_name="x",
            raw_data={"a": 1},
            llm_client=llm,
            prompt_registry=None,
        )
        assert result == {"a": 1}
        llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_parsed_json(self) -> None:
        llm = MagicMock()
        llm.chat = AsyncMock(return_value='{"title": "Refined", "content": "Body", "tags": ["t"]}')
        result = await refine_seed(
            plugin_name="x",
            raw_data={"some": "data", "with": "enough", "characters": "to refine"},
            llm_client=llm,
            prompt_registry=None,
        )
        assert result == {"title": "Refined", "content": "Body", "tags": ["t"]}

    @pytest.mark.asyncio
    async def test_falls_back_on_invalid_json(self) -> None:
        llm = MagicMock()
        llm.chat = AsyncMock(return_value="not json")
        raw = {"some": "data", "with": "enough", "characters": "to refine"}
        result = await refine_seed(
            plugin_name="x",
            raw_data=raw,
            llm_client=llm,
            prompt_registry=None,
        )
        assert result == raw

    @pytest.mark.asyncio
    async def test_falls_back_on_parsed_dict_without_required_keys(self) -> None:
        llm = MagicMock()
        llm.chat = AsyncMock(return_value='{"title": "no-content"}')
        raw = {"some": "data", "with": "enough", "characters": "to refine"}
        result = await refine_seed(
            plugin_name="x",
            raw_data=raw,
            llm_client=llm,
            prompt_registry=None,
        )
        assert result == raw

    @pytest.mark.asyncio
    async def test_swallows_runtime_error(self) -> None:
        # Public webhook contract — refinement must never raise.
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        raw = {"some": "data", "with": "enough", "characters": "to refine"}
        result = await refine_seed(
            plugin_name="x",
            raw_data=raw,
            llm_client=llm,
            prompt_registry=None,
        )
        assert result == raw

    @pytest.mark.asyncio
    async def test_swallows_oserror(self) -> None:
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=OSError("network"))
        raw = {"some": "data", "with": "enough", "characters": "to refine"}
        result = await refine_seed(
            plugin_name="x",
            raw_data=raw,
            llm_client=llm,
            prompt_registry=None,
        )
        assert result == raw

    @pytest.mark.asyncio
    async def test_uses_resolved_prompt(self) -> None:
        registry = MagicMock()
        registry.get = MagicMock(return_value="custom seed prompt")
        llm = MagicMock()
        llm.chat = AsyncMock(return_value='{"title": "x", "content": "y"}')
        await refine_seed(
            plugin_name="x",
            raw_data={"some": "data", "with": "enough", "characters": "to refine"},
            llm_client=llm,
            prompt_registry=registry,
        )
        # The system prompt passed to llm.chat must come from the registry.
        args = llm.chat.await_args
        assert args.kwargs["system"] == "custom seed prompt"
