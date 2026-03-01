"""Tests for the conversation-input plugin."""

import json
from unittest.mock import AsyncMock, MagicMock


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {"history_path": ".", "format": "jsonl"}
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "conversation_input", "plugins/conversation-input/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


# ── execute() tests ───────────────────────────────────────────────────


async def test_execute_reads_jsonl(tmp_path) -> None:
    execute_fn = _load_plugin()

    # Create two .jsonl files with messages
    f1 = tmp_path / "chat1.jsonl"
    f1.write_text(
        json.dumps({"role": "user", "content": "hello"})
        + "\n"
        + json.dumps({"role": "assistant", "content": "hi"})
        + "\n"
    )
    f2 = tmp_path / "chat2.jsonl"
    f2.write_text(json.dumps({"role": "user", "content": "bye"}) + "\n")

    ctx = _make_context(credentials={"history_path": str(tmp_path), "format": "jsonl"})
    result = await execute_fn(ctx)

    assert result == {"collected": 3}
    ctx.garden.write_seed.assert_awaited_once()
    messages = ctx.garden.write_seed.call_args[0][1]["messages"]
    assert len(messages) == 3


async def test_execute_reads_json(tmp_path) -> None:
    execute_fn = _load_plugin()

    # Create a .json file with an array of messages
    f1 = tmp_path / "conversations.json"
    f1.write_text(
        json.dumps(
            [
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": "answer"},
            ]
        )
    )

    ctx = _make_context(credentials={"history_path": str(tmp_path), "format": "json"})
    result = await execute_fn(ctx)

    assert result == {"collected": 2}
    ctx.garden.write_seed.assert_awaited_once()
    messages = ctx.garden.write_seed.call_args[0][1]["messages"]
    assert len(messages) == 2
    assert messages[0]["content"] == "question"


async def test_execute_reads_markdown(tmp_path) -> None:
    execute_fn = _load_plugin()

    # Create .md files
    f1 = tmp_path / "notes.md"
    f1.write_text("# My conversation\n\nSome interesting chat.")

    ctx = _make_context(credentials={"history_path": str(tmp_path), "format": "markdown"})
    result = await execute_fn(ctx)

    assert result == {"collected": 1}
    ctx.garden.write_seed.assert_awaited_once()
    messages = ctx.garden.write_seed.call_args[0][1]["messages"]
    assert len(messages) == 1
    assert messages[0]["file"] == "notes.md"
    assert "My conversation" in messages[0]["content"]


async def test_execute_empty_directory(tmp_path) -> None:
    execute_fn = _load_plugin()

    ctx = _make_context(credentials={"history_path": str(tmp_path), "format": "jsonl"})
    result = await execute_fn(ctx)

    assert result == {"collected": 0}
    # write_seed should NOT be called when there are no messages
    ctx.garden.write_seed.assert_not_awaited()


async def test_execute_updates_marker_file(tmp_path) -> None:
    execute_fn = _load_plugin()

    # Create a .jsonl file
    f1 = tmp_path / "chat.jsonl"
    f1.write_text(json.dumps({"role": "user", "content": "hi"}) + "\n")

    ctx = _make_context(credentials={"history_path": str(tmp_path), "format": "jsonl"})
    await execute_fn(ctx)

    marker = tmp_path / ".last_read"
    assert marker.exists()
    # Marker should contain a valid ISO timestamp
    from datetime import datetime

    timestamp_str = marker.read_text().strip()
    parsed = datetime.fromisoformat(timestamp_str)
    assert parsed.year >= 2026
