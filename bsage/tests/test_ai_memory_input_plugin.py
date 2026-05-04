"""Tests for plugins/ai-memory-input/plugin.py.

Generic AI memory uploader — accepts a single .md file or a .zip of them,
no longer tied to Claude Code's filesystem layout. Source hint
(claude-code/codex/opencode/custom) controls provenance + tags.
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


def _ctx(input_data=None):
    c = MagicMock()
    c.input_data = input_data or {}
    c.credentials = {}
    c.garden = AsyncMock()
    c.garden.write_garden = AsyncMock(return_value=Path("/vault/garden/preference/x.md"))
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
        assert ctx.garden.write_garden.await_count == 1

    @pytest.mark.asyncio
    async def test_title_from_first_h1(self, tmp_path: Path) -> None:
        f = tmp_path / "x.md"
        f.write_text("# My Title\nbody")
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        n = ctx.garden.write_garden.await_args.args[0]
        assert n.title == "My Title"

    @pytest.mark.asyncio
    async def test_falls_back_to_filename(self, tmp_path: Path) -> None:
        f = tmp_path / "no-heading.md"
        f.write_text("body without h1")
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        n = ctx.garden.write_garden.await_args.args[0]
        assert n.title == "no-heading"

    @pytest.mark.asyncio
    async def test_frontmatter_name_wins_over_h1(self, tmp_path: Path) -> None:
        # Real-world Claude Code memory files use frontmatter with a
        # human-readable name field. Title precedence: frontmatter.name >
        # first H1 > filename stem.
        f = tmp_path / "feedback_xyz.md"
        f.write_text(
            "---\nname: Report bug then fix it — no ask\ntype: feedback\n---\n# Some H1\nbody"
        )
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        n = ctx.garden.write_garden.await_args.args[0]
        assert n.title == "Report bug then fix it — no ask"

    @pytest.mark.asyncio
    async def test_frontmatter_title_field_also_works(self, tmp_path: Path) -> None:
        f = tmp_path / "x.md"
        f.write_text("---\ntitle: My Frontmatter Title\n---\nbody")
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        n = ctx.garden.write_garden.await_args.args[0]
        assert n.title == "My Frontmatter Title"

    @pytest.mark.asyncio
    async def test_h1_used_when_no_frontmatter_name(self, tmp_path: Path) -> None:
        f = tmp_path / "x.md"
        f.write_text("---\ntype: idea\n---\n# Real H1\nbody")
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        n = ctx.garden.write_garden.await_args.args[0]
        assert n.title == "Real H1"


class TestZipUpload:
    @pytest.mark.asyncio
    async def test_imports_each_md_in_zip(self, tmp_path: Path) -> None:
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

    @pytest.mark.asyncio
    async def test_zip_traversal_rejected(self, tmp_path: Path) -> None:
        zp = tmp_path / "evil.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("../escape.md", "x")
        execute = _load()
        ctx = _ctx({"path": str(zp)})
        with pytest.raises(ValueError, match="path traversal"):
            await execute(ctx)


class TestSourceHint:
    @pytest.mark.asyncio
    async def test_default_source_is_custom(self, tmp_path: Path) -> None:
        f = tmp_path / "x.md"
        f.write_text("# X")
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        n = ctx.garden.write_garden.await_args.args[0]
        assert n.tags == ["ai-memory", "custom"]
        assert n.extra_fields["provenance"]["source"] == "custom"

    @pytest.mark.asyncio
    async def test_claude_code_source_tag(self, tmp_path: Path) -> None:
        f = tmp_path / "x.md"
        f.write_text("# X")
        execute = _load()
        ctx = _ctx({"path": str(f), "source": "claude-code"})
        await execute(ctx)
        n = ctx.garden.write_garden.await_args.args[0]
        assert "claude-code" in n.tags
        assert n.extra_fields["provenance"]["source"] == "claude-code"

    @pytest.mark.asyncio
    async def test_unknown_source_falls_back_to_custom(self, tmp_path: Path) -> None:
        f = tmp_path / "x.md"
        f.write_text("# X")
        execute = _load()
        ctx = _ctx({"path": str(f), "source": "weird-tool"})
        await execute(ctx)
        n = ctx.garden.write_garden.await_args.args[0]
        # unknown source string is sanitized — only known values accepted
        assert n.extra_fields["provenance"]["source"] == "custom"


class TestProvenance:
    @pytest.mark.asyncio
    async def test_records_filename_and_sha256(self, tmp_path: Path) -> None:
        f = tmp_path / "memory.md"
        f.write_text(SAMPLE_MD)
        execute = _load()
        ctx = _ctx({"path": str(f)})
        await execute(ctx)
        n = ctx.garden.write_garden.await_args.args[0]
        prov = n.extra_fields["provenance"]
        assert prov["filename"] == "memory.md"
        assert "sha256" in prov
        assert len(prov["sha256"]) == 64


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
        # Either zero imports or error; clearer is error so users know
        assert result["imported"] == 0
