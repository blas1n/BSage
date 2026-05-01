"""Tests for bsage.garden.ingest_compiler — IngestCompiler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from bsage.garden.vault import Vault
from bsage.garden.writer import GardenWriter


class TestIngestCompilerCompile:
    """Test IngestCompiler.compile() core behaviour."""

    @pytest.fixture()
    def vault_and_writer(self, tmp_path: Path) -> tuple[Vault, GardenWriter]:
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        return vault, GardenWriter(vault)

    @pytest.fixture()
    def mock_llm(self) -> AsyncMock:
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value="[]")
        return llm

    @pytest.fixture()
    def mock_retriever(self) -> AsyncMock:
        retriever = AsyncMock()
        retriever.search = AsyncMock(return_value="No notes found.")
        return retriever

    @pytest.fixture()
    def mock_event_bus(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture()
    def compiler(
        self,
        vault_and_writer: tuple[Vault, GardenWriter],
        mock_llm: AsyncMock,
        mock_retriever: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> Any:
        from bsage.garden.ingest_compiler import IngestCompiler

        _, writer = vault_and_writer
        return IngestCompiler(
            garden_writer=writer,
            llm_client=mock_llm,
            retriever=mock_retriever,
            event_bus=mock_event_bus,
            max_updates=10,
        )

    @pytest.mark.asyncio
    async def test_compile_returns_compile_result(self, compiler: Any) -> None:
        """compile() should return a CompileResult dataclass."""
        from bsage.garden.ingest_compiler import CompileResult

        result = await compiler.compile("Some new information about AI", "telegram-input")
        assert isinstance(result, CompileResult)
        assert isinstance(result.notes_updated, int)
        assert isinstance(result.notes_created, int)
        assert isinstance(result.actions_taken, list)

    @pytest.mark.asyncio
    async def test_compile_calls_retriever_search(
        self, compiler: Any, mock_retriever: AsyncMock
    ) -> None:
        """compile() should search for related existing notes."""
        await compiler.compile("New insight about knowledge graphs", "chat")
        mock_retriever.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_compile_calls_llm_for_plan(self, compiler: Any, mock_llm: AsyncMock) -> None:
        """compile() should ask LLM to plan updates."""
        await compiler.compile("New data about project BSage", "telegram-input")
        mock_llm.chat.assert_awaited_once()
        # System prompt should mention ingest compilation
        call_kwargs = mock_llm.chat.call_args
        assert "system" in call_kwargs.kwargs or len(call_kwargs.args) >= 1

    @pytest.mark.asyncio
    async def test_compile_creates_new_notes(
        self,
        vault_and_writer: tuple[Vault, GardenWriter],
        mock_llm: AsyncMock,
        mock_retriever: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """When LLM plans 'create' actions, new garden notes should appear."""
        from bsage.garden.ingest_compiler import IngestCompiler

        vault, writer = vault_and_writer
        plan = json.dumps(
            [
                {
                    "action": "create",
                    "title": "Knowledge Graphs Overview",
                    "content": "Knowledge graphs connect entities and relationships.",
                    "note_type": "insight",
                    "reason": "New concept from seed",
                    "related": [],
                }
            ]
        )
        mock_llm.chat = AsyncMock(return_value=plan)

        compiler = IngestCompiler(
            garden_writer=writer,
            llm_client=mock_llm,
            retriever=mock_retriever,
            event_bus=mock_event_bus,
            max_updates=10,
        )
        result = await compiler.compile("Knowledge graphs are powerful", "telegram-input")

        assert result.notes_created == 1
        assert result.notes_updated == 0
        # Verify the note file was actually written
        insight_dir = vault.root / "insights"
        md_files = list(insight_dir.glob("*.md"))
        assert len(md_files) >= 1
        content = md_files[0].read_text()
        assert "Knowledge Graphs Overview" in content

    @pytest.mark.asyncio
    async def test_compile_updates_existing_notes(
        self,
        vault_and_writer: tuple[Vault, GardenWriter],
        mock_llm: AsyncMock,
        mock_retriever: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """When LLM plans 'update' actions, existing notes should be modified."""
        from bsage.garden.ingest_compiler import IngestCompiler

        vault, writer = vault_and_writer

        # Create an existing note first
        from bsage.garden.writer import GardenNote

        await writer.write_garden(
            GardenNote(
                title="AI Research",
                content="Early research on AI.",
                note_type="insight",
                source="manual",
            )
        )
        existing_path = "insights/ai-research.md"

        plan = json.dumps(
            [
                {
                    "action": "update",
                    "target_path": existing_path,
                    "title": "AI Research",
                    "content": "# AI Research\n\nUpdated: AI research now includes LLMs.",
                    "note_type": "insight",
                    "reason": "New information from seed",
                    "related": [],
                }
            ]
        )
        mock_llm.chat = AsyncMock(return_value=plan)

        compiler = IngestCompiler(
            garden_writer=writer,
            llm_client=mock_llm,
            retriever=mock_retriever,
            event_bus=mock_event_bus,
            max_updates=10,
        )
        result = await compiler.compile("LLMs are transforming AI", "chat")

        assert result.notes_updated == 1
        assert result.notes_created == 0
        updated = (vault.root / existing_path).read_text()
        assert "LLMs" in updated

    @pytest.mark.asyncio
    async def test_compile_appends_to_existing_notes(
        self,
        vault_and_writer: tuple[Vault, GardenWriter],
        mock_llm: AsyncMock,
        mock_retriever: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """When LLM plans 'append' actions, text should be appended."""
        from bsage.garden.ingest_compiler import IngestCompiler

        vault, writer = vault_and_writer
        from bsage.garden.writer import GardenNote

        await writer.write_garden(
            GardenNote(
                title="Machine Learning",
                content="ML is a subset of AI.",
                note_type="idea",
                source="manual",
            )
        )
        existing_path = "ideas/machine-learning.md"

        plan = json.dumps(
            [
                {
                    "action": "append",
                    "target_path": existing_path,
                    "title": "Machine Learning",
                    "content": "\n## New Section\n\nDeep learning advances.",
                    "note_type": "idea",
                    "reason": "Additional information",
                    "related": [],
                }
            ]
        )
        mock_llm.chat = AsyncMock(return_value=plan)

        compiler = IngestCompiler(
            garden_writer=writer,
            llm_client=mock_llm,
            retriever=mock_retriever,
            event_bus=mock_event_bus,
            max_updates=10,
        )
        result = await compiler.compile("Deep learning is advancing fast", "chat")

        assert result.notes_updated == 1
        content = (vault.root / existing_path).read_text()
        assert "Deep learning advances" in content

    @pytest.mark.asyncio
    async def test_compile_respects_max_updates(
        self,
        vault_and_writer: tuple[Vault, GardenWriter],
        mock_llm: AsyncMock,
        mock_retriever: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """compile() should cap the number of actions to max_updates."""
        from bsage.garden.ingest_compiler import IngestCompiler

        _, writer = vault_and_writer
        # LLM returns 5 create actions but max_updates is 2
        plan = json.dumps(
            [
                {
                    "action": "create",
                    "title": f"Note {i}",
                    "content": f"Content {i}",
                    "note_type": "idea",
                    "reason": "test",
                    "related": [],
                }
                for i in range(5)
            ]
        )
        mock_llm.chat = AsyncMock(return_value=plan)

        compiler = IngestCompiler(
            garden_writer=writer,
            llm_client=mock_llm,
            retriever=mock_retriever,
            event_bus=mock_event_bus,
            max_updates=2,
        )
        result = await compiler.compile("Many topics", "test")

        assert result.notes_created <= 2
        assert len(result.actions_taken) <= 2

    @pytest.mark.asyncio
    async def test_compile_emits_events(
        self,
        compiler: Any,
        mock_llm: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """compile() should emit INGEST_COMPILE_START and INGEST_COMPILE_COMPLETE events."""
        plan = json.dumps(
            [
                {
                    "action": "create",
                    "title": "Test",
                    "content": "Test content",
                    "note_type": "idea",
                    "reason": "test",
                    "related": [],
                }
            ]
        )
        mock_llm.chat = AsyncMock(return_value=plan)

        await compiler.compile("test data", "test-source")

        # Check that emit was called (via emit_event helper)
        assert mock_event_bus.emit.await_count >= 2

    @pytest.mark.asyncio
    async def test_compile_handles_empty_plan(self, compiler: Any, mock_llm: AsyncMock) -> None:
        """When LLM returns empty plan, compile() should return zero counts."""
        mock_llm.chat = AsyncMock(return_value="[]")

        result = await compiler.compile("irrelevant data", "test")

        assert result.notes_created == 0
        assert result.notes_updated == 0
        assert result.actions_taken == []

    @pytest.mark.asyncio
    async def test_compile_handles_malformed_llm_response(
        self, compiler: Any, mock_llm: AsyncMock
    ) -> None:
        """When LLM returns invalid JSON, compile() should not crash."""
        mock_llm.chat = AsyncMock(return_value="This is not JSON at all")

        result = await compiler.compile("some data", "test")

        assert result.notes_created == 0
        assert result.notes_updated == 0

    @pytest.mark.asyncio
    async def test_compile_handles_llm_errors_without_breaking_ingestion(
        self, compiler: Any, mock_llm: AsyncMock
    ) -> None:
        """Ingest compilation is best-effort; LLM/auth outages must not turn
        input ingestion into an HTTP 500."""
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("Missing API key"))

        result = await compiler.compile("some data", "bsnexus-input")

        assert result.notes_created == 0
        assert result.notes_updated == 0
        assert result.actions_taken == []

    @pytest.mark.asyncio
    async def test_compile_updates_cross_references(
        self,
        vault_and_writer: tuple[Vault, GardenWriter],
        mock_llm: AsyncMock,
        mock_retriever: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """When LLM specifies related links, they should be added to the note."""
        from bsage.garden.ingest_compiler import IngestCompiler

        _, writer = vault_and_writer
        plan = json.dumps(
            [
                {
                    "action": "create",
                    "title": "Neural Networks",
                    "content": "Neural networks are the basis of deep learning.",
                    "note_type": "insight",
                    "reason": "New concept",
                    "related": ["Machine Learning", "AI Research"],
                }
            ]
        )
        mock_llm.chat = AsyncMock(return_value=plan)

        compiler = IngestCompiler(
            garden_writer=writer,
            llm_client=mock_llm,
            retriever=mock_retriever,
            event_bus=mock_event_bus,
            max_updates=10,
        )
        result = await compiler.compile("Neural nets are powerful", "test")

        assert result.notes_created == 1
        vault = vault_and_writer[0]
        note_files = list((vault.root / "insights").glob("*.md"))
        content = note_files[0].read_text()
        assert "[[Machine Learning]]" in content or "Machine Learning" in content

    @pytest.mark.asyncio
    async def test_compile_skips_invalid_actions(
        self,
        vault_and_writer: tuple[Vault, GardenWriter],
        mock_llm: AsyncMock,
        mock_retriever: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """Actions with missing required fields should be skipped."""
        from bsage.garden.ingest_compiler import IngestCompiler

        _, writer = vault_and_writer
        plan = json.dumps(
            [
                {
                    "action": "create",
                    "title": "Valid",
                    "content": "ok",
                    "note_type": "idea",
                    "reason": "test",
                    "related": [],
                },
                {"action": "create"},  # missing fields
                {
                    "action": "update",
                    "target_path": "nonexistent/path.md",
                    "title": "X",
                    "content": "x",
                    "note_type": "idea",
                    "reason": "test",
                    "related": [],
                },
            ]
        )
        mock_llm.chat = AsyncMock(return_value=plan)

        compiler = IngestCompiler(
            garden_writer=writer,
            llm_client=mock_llm,
            retriever=mock_retriever,
            event_bus=mock_event_bus,
            max_updates=10,
        )
        result = await compiler.compile("test", "test")

        # Only the valid 'create' should succeed; malformed and nonexistent update should be skipped
        assert result.notes_created == 1
        assert len(result.actions_taken) == 1
