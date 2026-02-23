"""Tests for bsage.gateway.chat — vault-aware chat service."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bsage.core.prompt_registry import PromptRegistry
from bsage.gateway.chat import (
    _MAX_CONTEXT_CHARS,
    DEFAULT_CONTEXT_PATHS,
    build_system_prompt,
    gather_vault_context,
    handle_chat,
)


@pytest.fixture()
def prompt_registry(tmp_path):
    """Create a PromptRegistry with test templates."""
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "system.yaml").write_text("template: |\n  You are BSage, a personal AI assistant.\n")
    (d / "chat.yaml").write_text("template: |\n  {context_section}\n")
    return PromptRegistry(d)


def _make_garden_writer(notes_by_dir: dict[str, list[tuple[str, str]]] | None = None):
    """Create a mock GardenWriter.

    Args:
        notes_by_dir: Mapping of subdir -> list of (filename, content) tuples.
    """
    writer = AsyncMock()
    notes_by_dir = notes_by_dir or {}

    async def _read_notes(subdir):
        entries = notes_by_dir.get(subdir, [])
        return [Path(f"/vault/{subdir}/{name}") for name, _content in entries]

    async def _read_content(path):
        for entries in notes_by_dir.values():
            for name, content in entries:
                if path.name == name:
                    return content
        raise FileNotFoundError(path)

    writer.read_notes = AsyncMock(side_effect=_read_notes)
    writer.read_note_content = AsyncMock(side_effect=_read_content)
    writer.write_action = AsyncMock()
    return writer


def _make_llm_client(response: str = "Hello from BSage!"):
    """Create a mock LiteLLMClient."""
    client = AsyncMock()
    client.chat = AsyncMock(return_value=response)
    return client


class TestGatherVaultContext:
    """Test gather_vault_context reading and truncation."""

    async def test_reads_notes_from_paths(self) -> None:
        writer = _make_garden_writer(
            {
                "garden/idea": [("note-a.md", "Idea A content")],
                "garden/insight": [("note-b.md", "Insight B content")],
            }
        )
        result = await gather_vault_context(writer, ["garden/idea", "garden/insight"])

        assert "note-a.md" in result
        assert "Idea A content" in result
        assert "note-b.md" in result
        assert "Insight B content" in result

    async def test_reversed_order(self) -> None:
        writer = _make_garden_writer(
            {
                "garden/idea": [
                    ("01-first.md", "First"),
                    ("02-second.md", "Second"),
                    ("03-third.md", "Third"),
                ],
            }
        )
        result = await gather_vault_context(writer, ["garden/idea"])

        # reversed() means most recent (03) first
        idx_third = result.index("Third")
        idx_first = result.index("First")
        assert idx_third < idx_first

    async def test_truncation(self) -> None:
        big_content = "x" * 20_000
        writer = _make_garden_writer({"garden/idea": [("big.md", big_content)]})
        result = await gather_vault_context(writer, ["garden/idea"])

        assert len(result) <= _MAX_CONTEXT_CHARS + 50  # +50 for truncation message
        assert "...(truncated)" in result

    async def test_max_chars_stops_reading(self) -> None:
        writer = _make_garden_writer(
            {
                "garden/idea": [
                    ("a.md", "x" * 10_000),
                    ("b.md", "y" * 10_000),
                    ("c.md", "z" * 10_000),
                ],
            }
        )
        result = await gather_vault_context(writer, ["garden/idea"], max_chars=15_000)

        # Should not have read all three
        assert len(result) <= 15_050

    async def test_empty_vault(self) -> None:
        writer = _make_garden_writer({})
        result = await gather_vault_context(writer, ["garden/idea"])
        assert result == ""

    async def test_missing_directory_skipped(self) -> None:
        writer = AsyncMock()
        writer.read_notes = AsyncMock(side_effect=FileNotFoundError("no dir"))
        result = await gather_vault_context(writer, ["garden/nonexistent"])
        assert result == ""

    async def test_unreadable_note_skipped(self) -> None:
        writer = AsyncMock()
        writer.read_notes = AsyncMock(return_value=[Path("/vault/garden/idea/bad.md")])
        writer.read_note_content = AsyncMock(side_effect=OSError("read error"))
        result = await gather_vault_context(writer, ["garden/idea"])
        assert result == ""


class TestBuildSystemPrompt:
    """Test build_system_prompt with/without context."""

    def test_with_context(self, prompt_registry) -> None:
        prompt = build_system_prompt(prompt_registry, "## note.md\nSome content\n")
        assert "BSage" in prompt
        assert "knowledge base contains these notes" in prompt
        assert "note.md" in prompt

    def test_empty_context(self, prompt_registry) -> None:
        prompt = build_system_prompt(prompt_registry, "")
        assert "currently empty" in prompt

    def test_whitespace_context(self, prompt_registry) -> None:
        prompt = build_system_prompt(prompt_registry, "   \n  ")
        assert "currently empty" in prompt


class TestHandleChat:
    """Test handle_chat end-to-end orchestration."""

    async def test_basic_chat(self, prompt_registry) -> None:
        writer = _make_garden_writer({"garden/idea": [("note.md", "Test idea")]})
        llm = _make_llm_client("Here is my response.")

        result = await handle_chat(
            message="Hello",
            history=[],
            llm_client=llm,
            garden_writer=writer,
            prompt_registry=prompt_registry,
        )

        assert result == "Here is my response."
        llm.chat.assert_called_once()
        writer.write_action.assert_called_once()
        writer.write_seed.assert_called_once()

    async def test_history_passed_to_llm(self, prompt_registry) -> None:
        writer = _make_garden_writer({})
        llm = _make_llm_client("Response")

        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        await handle_chat(
            message="Follow up",
            history=history,
            llm_client=llm,
            garden_writer=writer,
            prompt_registry=prompt_registry,
        )

        messages = llm.chat.call_args.kwargs["messages"]
        # history + new user message
        assert len(messages) == 3
        assert messages[-1] == {"role": "user", "content": "Follow up"}

    async def test_custom_context_paths(self, prompt_registry) -> None:
        writer = _make_garden_writer({"custom/path": [("note.md", "Custom content")]})
        llm = _make_llm_client("Ok")

        await handle_chat(
            message="Test",
            history=[],
            llm_client=llm,
            garden_writer=writer,
            prompt_registry=prompt_registry,
            context_paths=["custom/path"],
        )

        writer.read_notes.assert_called_with("custom/path")

    async def test_default_context_paths_used(self, prompt_registry) -> None:
        writer = _make_garden_writer({})
        llm = _make_llm_client("Ok")

        await handle_chat(
            message="Test",
            history=[],
            llm_client=llm,
            garden_writer=writer,
            prompt_registry=prompt_registry,
        )

        # Should call read_notes for each default path
        called_dirs = [call.args[0] for call in writer.read_notes.call_args_list]
        assert called_dirs == DEFAULT_CONTEXT_PATHS

    async def test_action_logged(self, prompt_registry) -> None:
        writer = _make_garden_writer({})
        llm = _make_llm_client("My answer")

        await handle_chat(
            message="What should I do?",
            history=[],
            llm_client=llm,
            garden_writer=writer,
            prompt_registry=prompt_registry,
        )

        writer.write_action.assert_called_once()
        action_args = writer.write_action.call_args
        assert action_args.args[0] == "chat"
        assert "What should I do?" in action_args.args[1]

    async def test_transcript_saved_as_seed(self, prompt_registry) -> None:
        writer = _make_garden_writer({})
        llm = _make_llm_client("Full response\nwith newlines")

        await handle_chat(
            message="Tell me something",
            history=[],
            llm_client=llm,
            garden_writer=writer,
            prompt_registry=prompt_registry,
        )

        writer.write_seed.assert_called_once()
        seed_args = writer.write_seed.call_args
        assert seed_args.args[0] == "chat"
        assert seed_args.args[1]["user"] == "Tell me something"
        assert seed_args.args[1]["assistant"] == "Full response\nwith newlines"
