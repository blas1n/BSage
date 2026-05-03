"""Tests for plugins/chatgpt-memory-input/plugin.py."""

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


def _ctx(input_data=None):
    c = MagicMock()
    c.input_data = input_data or {}
    c.credentials = {}
    c.garden = AsyncMock()
    c.garden.write_garden = AsyncMock(return_value=Path("/vault/garden/insight/x.md"))
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
    async def test_imports_each_conversation(self, tmp_path: Path) -> None:
        f = tmp_path / "conversations.json"
        f.write_text(json.dumps(SAMPLE_CONVERSATIONS))

        execute = _load()
        ctx = _ctx({"path": str(f)})
        result = await execute(ctx)

        assert result["imported"] == 2
        assert ctx.garden.write_garden.await_count == 2

    @pytest.mark.asyncio
    async def test_note_carries_external_id(self, tmp_path: Path) -> None:
        f = tmp_path / "c.json"
        f.write_text(json.dumps(SAMPLE_CONVERSATIONS))
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)

        notes = [c.args[0] for c in ctx.garden.write_garden.await_args_list]
        ids = {n.extra_fields["provenance"]["external_id"] for n in notes}
        assert ids == {"conv-1", "conv-2"}
        assert all(n.note_type == "insight" for n in notes)
        assert all("chatgpt" in n.tags for n in notes)

    @pytest.mark.asyncio
    async def test_message_text_preserved_in_body(self, tmp_path: Path) -> None:
        f = tmp_path / "c.json"
        f.write_text(json.dumps(SAMPLE_CONVERSATIONS))
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)

        notes = {
            c.args[0].extra_fields["provenance"]["external_id"]: c.args[0]
            for c in ctx.garden.write_garden.await_args_list
        }
        assert "How do generators work?" in notes["conv-1"].content
        assert "Generators yield values lazily." in notes["conv-1"].content


class TestChatGPTMemories:
    @pytest.mark.asyncio
    async def test_imports_string_and_dict_memories(self, tmp_path: Path) -> None:
        f = tmp_path / "memory.json"
        f.write_text(json.dumps(SAMPLE_MEMORIES))
        execute = _load()
        ctx = _ctx({"path": str(f)})
        result = await execute(ctx)

        assert result["imported"] == 2
        notes = [c.args[0] for c in ctx.garden.write_garden.await_args_list]
        assert all(n.note_type == "preference" for n in notes)


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
