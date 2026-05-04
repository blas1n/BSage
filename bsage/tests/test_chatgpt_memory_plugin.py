"""Tests for plugins/chatgpt-memory-input/plugin.py.

Plugin writes one SEED per conversation/memory and invokes
``IngestCompiler`` for each — it never produces garden notes
directly.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load():
    spec = importlib.util.spec_from_file_location(
        "chatgpt_memory_input", "plugins/chatgpt-memory-input/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


def _ctx(input_data=None, *, with_compiler: bool = True, batch_result=None):
    c = MagicMock()
    c.input_data = input_data or {}
    c.credentials = {}
    c.logger = MagicMock()
    c.garden = AsyncMock()
    c.garden.write_seed = AsyncMock(return_value=Path("/vault/seeds/chatgpt/x.md"))
    if with_compiler:
        c.ingest_compiler = AsyncMock()
        if batch_result is None:
            batch_result = MagicMock(
                notes_created=2, notes_updated=0, llm_calls=1, actions_taken=[]
            )
        c.ingest_compiler.compile_batch = AsyncMock(return_value=batch_result)
    else:
        c.ingest_compiler = None
    return c


SAMPLE_CONVERSATIONS = [
    {
        "id": "conv-1",
        "title": "Python question",
        "create_time": 1714000000,
        "mapping": {
            "n1": {
                "message": {
                    "author": {"role": "user"},
                    "create_time": 1.0,
                    "content": {"parts": ["How do generators work?"]},
                }
            },
            "n2": {
                "message": {
                    "author": {"role": "assistant"},
                    "create_time": 2.0,
                    "content": {"parts": ["Generators yield values lazily."]},
                }
            },
        },
    },
    {
        "id": "conv-2",
        "title": "Migration help",
        "create_time": 1714200000,
        "mapping": {},
    },
]


SAMPLE_MEMORIES = {
    "memories": [
        "User prefers concise answers",
        {"id": "m2", "content": "Works in Python", "title": "Stack"},
    ]
}


class TestChatGPTConversations:
    @pytest.mark.asyncio
    async def test_writes_seeds_then_one_batched_compile(self, tmp_path: Path) -> None:
        f = tmp_path / "conversations.json"
        f.write_text(json.dumps(SAMPLE_CONVERSATIONS))

        execute = _load()
        ctx = _ctx({"path": str(f)})
        result = await execute(ctx)

        assert result["imported"] == 2
        assert ctx.garden.write_seed.await_count == 2
        assert ctx.ingest_compiler.compile_batch.await_count == 1
        kwargs = ctx.ingest_compiler.compile_batch.await_args.kwargs
        assert len(kwargs["items"]) == 2

    @pytest.mark.asyncio
    async def test_seed_carries_external_id(self, tmp_path: Path) -> None:
        f = tmp_path / "c.json"
        f.write_text(json.dumps(SAMPLE_CONVERSATIONS))
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)

        seeds = [c.args[1] for c in ctx.garden.write_seed.await_args_list]
        ids = {s["provenance"]["external_id"] for s in seeds}
        assert ids == {"conv-1", "conv-2"}
        assert all("chatgpt" in s["tags"] for s in seeds)

    @pytest.mark.asyncio
    async def test_message_text_preserved_in_seed_content(self, tmp_path: Path) -> None:
        f = tmp_path / "c.json"
        f.write_text(json.dumps(SAMPLE_CONVERSATIONS))
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)

        seeds_by_id = {
            c.args[1]["provenance"]["external_id"]: c.args[1]
            for c in ctx.garden.write_seed.await_args_list
        }
        assert "How do generators work?" in seeds_by_id["conv-1"]["content"]
        assert "Generators yield values lazily." in seeds_by_id["conv-1"]["content"]


class TestChatGPTMemories:
    @pytest.mark.asyncio
    async def test_writes_a_seed_per_memory(self, tmp_path: Path) -> None:
        f = tmp_path / "memory.json"
        f.write_text(json.dumps(SAMPLE_MEMORIES))
        execute = _load()
        ctx = _ctx({"path": str(f)})
        result = await execute(ctx)

        assert result["imported"] == 2
        seeds = [c.args[1] for c in ctx.garden.write_seed.await_args_list]
        assert all(s["provenance"]["kind"] == "saved_memory" for s in seeds)
        assert ctx.ingest_compiler.compile_batch.await_count == 1


class TestCompilerWiring:
    @pytest.mark.asyncio
    async def test_propagates_batch_compile_counts(self, tmp_path: Path) -> None:
        f = tmp_path / "c.json"
        f.write_text(json.dumps(SAMPLE_CONVERSATIONS))
        execute = _load()
        ctx = _ctx(
            {"path": str(f)},
            batch_result=MagicMock(notes_created=1, notes_updated=2, llm_calls=1, actions_taken=[]),
        )
        result = await execute(ctx)
        assert result["notes_created"] == 1
        assert result["notes_updated"] == 2
        assert result["llm_calls"] == 1

    @pytest.mark.asyncio
    async def test_batch_failure_keeps_seeds(self, tmp_path: Path) -> None:
        f = tmp_path / "c.json"
        f.write_text(json.dumps(SAMPLE_CONVERSATIONS))
        execute = _load()
        ctx = _ctx({"path": str(f)})
        ctx.ingest_compiler.compile_batch = AsyncMock(side_effect=RuntimeError("boom"))
        result = await execute(ctx)
        assert result["imported"] == 2
        assert result["compile_error"] == "boom"

    @pytest.mark.asyncio
    async def test_runs_without_compiler(self, tmp_path: Path) -> None:
        f = tmp_path / "c.json"
        f.write_text(json.dumps(SAMPLE_CONVERSATIONS))
        execute = _load()
        ctx = _ctx({"path": str(f)}, with_compiler=False)
        result = await execute(ctx)
        assert result["imported"] == 2
        assert result["compiler_available"] is False


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_no_path_returns_error(self) -> None:
        execute = _load()
        ctx = _ctx()
        result = await execute(ctx)
        assert result["imported"] == 0
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        execute = _load()
        ctx = _ctx({"path": str(tmp_path / "missing.json")})
        result = await execute(ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("{not json")
        execute = _load()
        ctx = _ctx({"path": str(f)})
        result = await execute(ctx)
        assert "error" in result
