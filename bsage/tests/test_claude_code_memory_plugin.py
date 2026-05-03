"""Tests for plugins/claude-code-memory-input/plugin.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load():
    spec = importlib.util.spec_from_file_location(
        "claude_code_memory_input", "plugins/claude-code-memory-input/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


def _ctx(input_data=None, credentials=None):
    c = MagicMock()
    c.input_data = input_data or {}
    c.credentials = credentials or {}
    c.garden = AsyncMock()
    c.garden.write_garden = AsyncMock(return_value=Path("/vault/garden/preference/x.md"))
    return c


def _seed_claude_root(root: Path) -> None:
    """Build a fake ~/.claude tree."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text("# User Memory\n\nGlobal preference X")

    proj = root / "projects" / "my-project"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "CLAUDE.md").write_text("# Project rules\n\nUse uv")
    (proj / "MEMORY.md").write_text("# Memory index\n\nIndex content")

    mem = proj / "memory"
    mem.mkdir(exist_ok=True)
    (mem / "user_role.md").write_text("# Role\n\nSE")


class TestClaudeCodeMemory:
    @pytest.mark.asyncio
    async def test_imports_user_and_project_files(self, tmp_path: Path) -> None:
        _seed_claude_root(tmp_path)
        execute = _load()
        ctx = _ctx({"claude_root": str(tmp_path)})
        result = await execute(ctx)
        # 1 user CLAUDE.md + 2 project (CLAUDE + MEMORY) + 1 memory subdir file = 4
        assert result["imported"] == 4

    @pytest.mark.asyncio
    async def test_provenance_includes_sha256_and_mtime(self, tmp_path: Path) -> None:
        _seed_claude_root(tmp_path)
        execute = _load()
        ctx = _ctx({"claude_root": str(tmp_path)})
        await execute(ctx)
        notes = [c.args[0] for c in ctx.garden.write_garden.await_args_list]
        for n in notes:
            prov = n.extra_fields["provenance"]
            assert prov["source"] == "claude-code"
            assert "sha256" in prov
            assert "mtime" in prov
            assert "file_path" in prov

    @pytest.mark.asyncio
    async def test_project_slug_in_tags(self, tmp_path: Path) -> None:
        _seed_claude_root(tmp_path)
        execute = _load()
        ctx = _ctx({"claude_root": str(tmp_path)})
        await execute(ctx)
        notes = [c.args[0] for c in ctx.garden.write_garden.await_args_list]
        # User-level note tagged "user", project notes tagged "my-project"
        tags = {tuple(n.tags) for n in notes}
        assert any("user" in t for t in tags)
        assert any("my-project" in t for t in tags)

    @pytest.mark.asyncio
    async def test_include_projects_false_skips_them(self, tmp_path: Path) -> None:
        _seed_claude_root(tmp_path)
        execute = _load()
        ctx = _ctx({"claude_root": str(tmp_path), "include_projects": False})
        result = await execute(ctx)
        assert result["imported"] == 1  # only user-level CLAUDE.md

    @pytest.mark.asyncio
    async def test_missing_root_returns_error(self, tmp_path: Path) -> None:
        execute = _load()
        ctx = _ctx({"claude_root": str(tmp_path / "missing")})
        result = await execute(ctx)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_title_from_first_h1(self, tmp_path: Path) -> None:
        _seed_claude_root(tmp_path)
        execute = _load()
        ctx = _ctx({"claude_root": str(tmp_path)})
        await execute(ctx)
        titles = {c.args[0].title for c in ctx.garden.write_garden.await_args_list}
        assert "User Memory" in titles
        assert "Project rules" in titles
