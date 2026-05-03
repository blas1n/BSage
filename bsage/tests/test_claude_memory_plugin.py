"""Tests for plugins/claude-memory-input/plugin.py."""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load():
    spec = importlib.util.spec_from_file_location(
        "claude_memory_input", "plugins/claude-memory-input/plugin.py"
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


SAMPLE_CONVS = [
    {
        "uuid": "abc-1",
        "name": "First chat",
        "created_at": "2026-04-01T10:00:00Z",
        "messages": [
            {"sender": "human", "text": "Hello"},
            {"sender": "assistant", "text": "Hi there"},
        ],
    },
    {
        "uuid": "abc-2",
        "name": "Second",
        "created_at": "2026-04-02T10:00:00Z",
        "messages": [],
    },
]


class TestClaudeMemoryJson:
    @pytest.mark.asyncio
    async def test_imports_each_conversation(self, tmp_path: Path) -> None:
        f = tmp_path / "conversations.json"
        f.write_text(json.dumps(SAMPLE_CONVS))
        execute = _load()
        ctx = _ctx({"path": str(f)})
        result = await execute(ctx)
        assert result["imported"] == 2

    @pytest.mark.asyncio
    async def test_external_id_uses_uuid(self, tmp_path: Path) -> None:
        f = tmp_path / "conversations.json"
        f.write_text(json.dumps(SAMPLE_CONVS))
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        notes = [c.args[0] for c in ctx.garden.write_garden.await_args_list]
        ids = {n.extra_fields["provenance"]["external_id"] for n in notes}
        assert ids == {"abc-1", "abc-2"}

    @pytest.mark.asyncio
    async def test_message_text_in_body(self, tmp_path: Path) -> None:
        f = tmp_path / "conversations.json"
        f.write_text(json.dumps(SAMPLE_CONVS))
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        notes = [c.args[0] for c in ctx.garden.write_garden.await_args_list]
        first = next(n for n in notes if n.title == "First chat")
        assert "Hello" in first.content
        assert "Hi there" in first.content


class TestClaudeMemoryZip:
    @pytest.mark.asyncio
    async def test_imports_from_zip(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "claude-export.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("conversations.json", json.dumps(SAMPLE_CONVS))
        execute = _load()
        ctx = _ctx({"path": str(zip_path)})
        result = await execute(ctx)
        assert result["imported"] == 2

    @pytest.mark.asyncio
    async def test_zip_traversal_rejected(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../escape.json", "{}")
        execute = _load()
        ctx = _ctx({"path": str(zip_path)})
        with pytest.raises(ValueError, match="path traversal"):
            await execute(ctx)


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_missing_path(self) -> None:
        execute = _load()
        ctx = _ctx()
        result = await execute(ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_zip_without_conversations_json(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "noop")
        execute = _load()
        ctx = _ctx({"path": str(zip_path)})
        result = await execute(ctx)
        assert "error" in result
