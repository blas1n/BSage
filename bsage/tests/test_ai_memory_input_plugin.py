"""Tests for plugins/ai-memory-input/plugin.py.

Plugin writes each markdown file as a SEED + invokes IngestCompiler —
it never writes garden notes itself, since external surfaces are
restricted to the seed-only garden interface.
"""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load():
    spec = importlib.util.spec_from_file_location(
        "ai_memory_input", "plugins/ai-memory-input/plugin.py"
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
    c.garden.write_seed = AsyncMock(return_value=Path("/vault/seeds/ai-memory/x.md"))
    if with_compiler:
        c.ingest_compiler = AsyncMock()
        if batch_result is None:
            batch_result = MagicMock(
                notes_created=3, notes_updated=0, llm_calls=1, actions_taken=[]
            )
        c.ingest_compiler.compile_batch = AsyncMock(return_value=batch_result)
    else:
        c.ingest_compiler = None
    return c


SAMPLE_MD = """\
# Project rules

- Always use uv
- Python 3.11+
"""


class TestSingleMarkdown:
    @pytest.mark.asyncio
    async def test_imports_a_single_md_file(self, tmp_path: Path) -> None:
        f = tmp_path / "memory.md"
        f.write_text(SAMPLE_MD)
        execute = _load()
        ctx = _ctx({"path": str(f)})
        result = await execute(ctx)
        assert result["imported"] == 1
        assert ctx.garden.write_seed.await_count == 1
        # Single batched compile call regardless of file count.
        assert ctx.ingest_compiler.compile_batch.await_count == 1

    @pytest.mark.asyncio
    async def test_seed_carries_raw_content_and_provenance(self, tmp_path: Path) -> None:
        f = tmp_path / "memory.md"
        f.write_text(SAMPLE_MD)
        execute = _load()
        ctx = _ctx({"path": str(f), "source": "claude-code"})
        await execute(ctx)
        source_arg, data_arg = ctx.garden.write_seed.await_args.args
        assert source_arg == "ai-memory/claude-code"
        assert data_arg["content"] == SAMPLE_MD
        assert data_arg["provenance"]["filename"] == "memory.md"
        assert len(data_arg["provenance"]["sha256"]) == 64
        assert data_arg["provenance"]["source"] == "claude-code"

    @pytest.mark.asyncio
    async def test_title_from_first_h1(self, tmp_path: Path) -> None:
        f = tmp_path / "x.md"
        f.write_text("# My Title\nbody")
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        data = ctx.garden.write_seed.await_args.args[1]
        assert data["title"] == "My Title"

    @pytest.mark.asyncio
    async def test_falls_back_to_filename(self, tmp_path: Path) -> None:
        f = tmp_path / "no-heading.md"
        f.write_text("body without h1")
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        data = ctx.garden.write_seed.await_args.args[1]
        assert data["title"] == "no-heading"

    @pytest.mark.asyncio
    async def test_frontmatter_name_wins_over_h1(self, tmp_path: Path) -> None:
        f = tmp_path / "feedback_xyz.md"
        f.write_text(
            "---\nname: Report bug then fix it — no ask\ntype: feedback\n---\n# Some H1\nbody"
        )
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        data = ctx.garden.write_seed.await_args.args[1]
        assert data["title"] == "Report bug then fix it — no ask"


class TestZipUpload:
    @pytest.mark.asyncio
    async def test_writes_seeds_then_one_batched_compile(self, tmp_path: Path) -> None:
        zp = tmp_path / "memories.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("a.md", "# A\nbody")
            zf.writestr("b.md", "# B\nbody")
            zf.writestr("nested/c.md", "# C\nbody")
            zf.writestr("ignore.txt", "not markdown")  # should be skipped
        execute = _load()
        ctx = _ctx({"path": str(zp)})
        result = await execute(ctx)
        assert result["imported"] == 3
        assert ctx.garden.write_seed.await_count == 3
        # Three files → still ONE compile call (the whole point of batching).
        assert ctx.ingest_compiler.compile_batch.await_count == 1
        # The single call sees all three items.
        kwargs = ctx.ingest_compiler.compile_batch.await_args.kwargs
        assert len(kwargs["items"]) == 3

    @pytest.mark.asyncio
    async def test_zip_traversal_rejected(self, tmp_path: Path) -> None:
        zp = tmp_path / "evil.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("../escape.md", "x")
        execute = _load()
        ctx = _ctx({"path": str(zp)})
        with pytest.raises(ValueError, match="path traversal"):
            await execute(ctx)


class TestCompilerWiring:
    @pytest.mark.asyncio
    async def test_batch_items_carry_source_hint_and_filename(self, tmp_path: Path) -> None:
        f = tmp_path / "rules.md"
        f.write_text("# Rules\nuse uv")
        execute = _load()
        ctx = _ctx({"path": str(f), "source": "claude-code"})
        await execute(ctx)
        kwargs = ctx.ingest_compiler.compile_batch.await_args.kwargs
        assert kwargs["seed_source"] == "ai-memory-input/claude-code"
        assert len(kwargs["items"]) == 1
        item = kwargs["items"][0]
        assert "rules.md" in item.label
        assert "use uv" in item.content

    @pytest.mark.asyncio
    async def test_propagates_batch_compile_counts(self, tmp_path: Path) -> None:
        zp = tmp_path / "memories.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("a.md", "# A\nbody")
            zf.writestr("b.md", "# B\nbody")
        execute = _load()
        ctx = _ctx(
            {"path": str(zp)},
            batch_result=MagicMock(notes_created=2, notes_updated=1, llm_calls=1, actions_taken=[]),
        )
        result = await execute(ctx)
        assert result["notes_created"] == 2
        assert result["notes_updated"] == 1
        assert result["llm_calls"] == 1
        assert result["compile_error"] is None

    @pytest.mark.asyncio
    async def test_batch_compile_failure_is_surfaced_but_seeds_kept(self, tmp_path: Path) -> None:
        # If the LLM batch fails, seeds remain on disk and the error is
        # reported back so the user knows to re-run compile later.
        zp = tmp_path / "memories.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("a.md", "# A\nbody")
            zf.writestr("b.md", "# B\nbody")
        execute = _load()
        ctx = _ctx({"path": str(zp)})
        ctx.ingest_compiler.compile_batch = AsyncMock(side_effect=RuntimeError("boom"))
        result = await execute(ctx)
        assert result["imported"] == 2
        assert result["notes_created"] == 0
        assert result["compile_error"] == "boom"
        assert ctx.garden.write_seed.await_count == 2

    @pytest.mark.asyncio
    async def test_runs_without_compiler_writing_seeds_only(self, tmp_path: Path) -> None:
        # When the compiler isn't available, we still preserve the user's
        # input as seeds — they can be compiled later.
        f = tmp_path / "x.md"
        f.write_text("# X\nbody")
        execute = _load()
        ctx = _ctx({"path": str(f)}, with_compiler=False)
        result = await execute(ctx)
        assert result["imported"] == 1
        assert result["compiler_available"] is False
        assert ctx.garden.write_seed.await_count == 1


class TestSourceHint:
    @pytest.mark.asyncio
    async def test_default_source_is_custom(self, tmp_path: Path) -> None:
        f = tmp_path / "x.md"
        f.write_text("# X")
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        source_arg, data = ctx.garden.write_seed.await_args.args
        assert source_arg == "ai-memory/custom"
        assert data["provenance"]["source"] == "custom"

    @pytest.mark.asyncio
    async def test_unknown_source_falls_back_to_custom(self, tmp_path: Path) -> None:
        f = tmp_path / "x.md"
        f.write_text("# X")
        execute = _load()
        ctx = _ctx({"path": str(f), "source": "weird-tool"})
        await execute(ctx)
        data = ctx.garden.write_seed.await_args.args[1]
        assert data["provenance"]["source"] == "custom"


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_no_path_returns_error(self) -> None:
        execute = _load()
        ctx = _ctx()
        result = await execute(ctx)
        assert "error" in result
        assert result["imported"] == 0

    @pytest.mark.asyncio
    async def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        execute = _load()
        ctx = _ctx({"path": str(tmp_path / "nope.md")})
        result = await execute(ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unsupported_extension_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "data.txt"
        f.write_text("not a markdown")
        execute = _load()
        ctx = _ctx({"path": str(f)})
        result = await execute(ctx)
        assert result["imported"] == 0
