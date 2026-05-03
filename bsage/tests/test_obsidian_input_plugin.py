"""Tests for plugins/obsidian-input/plugin.py."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load_plugin():
    spec = importlib.util.spec_from_file_location(
        "obsidian_input", "plugins/obsidian-input/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


def _make_context(input_data=None, credentials=None):
    ctx = MagicMock()
    ctx.input_data = input_data or {}
    ctx.credentials = credentials or {}
    ctx.garden = AsyncMock()
    ctx.garden.write_garden = AsyncMock(return_value=Path("/vault/garden/idea/x.md"))
    return ctx


def _seed_vault(root: Path) -> None:
    """Create a small Obsidian vault on disk."""
    (root / "garden").mkdir(parents=True, exist_ok=True)
    (root / ".obsidian").mkdir(exist_ok=True)
    (root / ".obsidian" / "config").write_text("{}")  # should be skipped

    (root / "intro.md").write_text(
        "---\ntitle: Intro\ntype: idea\ntags: [welcome]\n---\n# Intro\nHello [[Other]]"
    )
    (root / "garden" / "deep.md").write_text("---\ntype: insight\nkey: value\n---\n# Deep\nBody")
    (root / "no_frontmatter.md").write_text("# No Frontmatter\nBody only")


class TestObsidianInputLocalPath:
    @pytest.mark.asyncio
    async def test_imports_all_md_files(self, tmp_path: Path) -> None:
        _seed_vault(tmp_path)
        execute = _load_plugin()
        ctx = _make_context(input_data={"vault_path": str(tmp_path)})

        result = await execute(ctx)

        assert result["imported"] == 3
        assert ctx.garden.write_garden.await_count == 3

    @pytest.mark.asyncio
    async def test_skips_dotted_dirs(self, tmp_path: Path) -> None:
        _seed_vault(tmp_path)
        # add a hidden file that should be skipped
        (tmp_path / ".obsidian" / "should-skip.md").write_text("hidden")
        execute = _load_plugin()
        ctx = _make_context(input_data={"vault_path": str(tmp_path)})
        await execute(ctx)
        # Only the 3 visible md files
        assert ctx.garden.write_garden.await_count == 3

    @pytest.mark.asyncio
    async def test_note_carries_provenance(self, tmp_path: Path) -> None:
        _seed_vault(tmp_path)
        execute = _load_plugin()
        ctx = _make_context(input_data={"vault_path": str(tmp_path)})
        await execute(ctx)

        notes = [c.args[0] for c in ctx.garden.write_garden.await_args_list]
        for n in notes:
            assert n.source == "obsidian-input"
            assert n.extra_fields["provenance"]["source"] == "obsidian"
            assert "original_path" in n.extra_fields["provenance"]

    @pytest.mark.asyncio
    async def test_frontmatter_title_takes_precedence(self, tmp_path: Path) -> None:
        _seed_vault(tmp_path)
        execute = _load_plugin()
        ctx = _make_context(input_data={"vault_path": str(tmp_path)})
        await execute(ctx)

        notes = {
            c.args[0].extra_fields["provenance"]["original_path"]: c.args[0]
            for c in ctx.garden.write_garden.await_args_list
        }
        intro = notes["intro.md"]
        assert intro.title == "Intro"
        assert intro.note_type == "idea"
        assert intro.tags == ["welcome"]

    @pytest.mark.asyncio
    async def test_credentials_vault_path_is_default(self, tmp_path: Path) -> None:
        _seed_vault(tmp_path)
        execute = _load_plugin()
        ctx = _make_context(credentials={"vault_path": str(tmp_path)})
        result = await execute(ctx)
        assert result["imported"] == 3

    @pytest.mark.asyncio
    async def test_input_data_overrides_credentials(self, tmp_path: Path) -> None:
        # tmp_path = override; credential dir has no md files
        empty = tmp_path / "empty"
        empty.mkdir()
        seeded = tmp_path / "seeded"
        seeded.mkdir()
        _seed_vault(seeded)

        execute = _load_plugin()
        ctx = _make_context(
            input_data={"vault_path": str(seeded)},
            credentials={"vault_path": str(empty)},
        )
        result = await execute(ctx)
        assert result["imported"] == 3

    @pytest.mark.asyncio
    async def test_no_source_returns_zero(self, tmp_path: Path) -> None:
        execute = _load_plugin()
        ctx = _make_context()
        result = await execute(ctx)
        assert result["imported"] == 0
        assert "error" in result


class TestObsidianInputZip:
    @pytest.mark.asyncio
    async def test_imports_from_zip_path(self, tmp_path: Path) -> None:
        # Build a zip vault
        vault_dir = tmp_path / "src"
        _seed_vault(vault_dir)
        zip_path = tmp_path / "vault.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for p in vault_dir.rglob("*.md"):
                zf.write(p, arcname=str(p.relative_to(vault_dir)))

        execute = _load_plugin()
        ctx = _make_context(input_data={"path": str(zip_path)})
        result = await execute(ctx)
        assert result["imported"] >= 1

    @pytest.mark.asyncio
    async def test_zip_with_traversal_path_rejected(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../escape.md", "# Escape")

        execute = _load_plugin()
        ctx = _make_context(input_data={"path": str(zip_path)})
        with pytest.raises(ValueError, match="path traversal"):
            await execute(ctx)
