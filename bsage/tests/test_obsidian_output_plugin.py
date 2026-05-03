"""Tests for plugins/obsidian-output/plugin.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load_plugin():
    spec = importlib.util.spec_from_file_location(
        "obsidian_output", "plugins/obsidian-output/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


def _make_context(tmp_vault: Path, input_data=None, credentials=None):
    ctx = MagicMock()
    ctx.input_data = input_data or {}
    ctx.credentials = credentials or {}

    # Build a fake garden + vault on disk so read_notes returns real paths
    (tmp_vault / "garden" / "idea").mkdir(parents=True, exist_ok=True)
    (tmp_vault / "seeds" / "x").mkdir(parents=True, exist_ok=True)
    n1 = tmp_vault / "garden" / "idea" / "a.md"
    n1.write_text("---\ntype: idea\n---\n# A\nBody A")
    n2 = tmp_vault / "garden" / "idea" / "b.md"
    n2.write_text("---\ntype: idea\n---\n# B\nBody B")
    s1 = tmp_vault / "seeds" / "x" / "raw.md"
    s1.write_text("# Raw seed")

    ctx.garden = MagicMock()
    ctx.garden._vault = MagicMock()
    ctx.garden._vault.root = tmp_vault

    async def _read_notes(subdir: str) -> list[Path]:
        path = tmp_vault / subdir
        if not path.is_dir():
            return []
        return sorted(path.rglob("*.md"))

    async def _read_content(p: Path) -> str:
        return p.read_text(encoding="utf-8")

    ctx.garden.read_notes = AsyncMock(side_effect=_read_notes)
    ctx.garden.read_note_content = AsyncMock(side_effect=_read_content)
    return ctx


class TestObsidianOutput:
    @pytest.mark.asyncio
    async def test_writes_garden_and_seeds_by_default(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        out = tmp_path / "out"
        ctx = _make_context(vault, credentials={"output_vault_path": str(out)})
        execute = _load_plugin()

        result = await execute(ctx)
        assert result["written"] == 3
        assert result["skipped"] == 0
        assert (out / "garden" / "idea" / "a.md").exists()
        assert (out / "seeds" / "x" / "raw.md").exists()

    @pytest.mark.asyncio
    async def test_skips_existing_files_without_overwrite(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        out = tmp_path / "out"
        ctx = _make_context(vault, credentials={"output_vault_path": str(out)})
        execute = _load_plugin()

        await execute(ctx)
        # Second run — all files already exist, should skip
        result = await execute(ctx)
        assert result["written"] == 0
        assert result["skipped"] == 3

    @pytest.mark.asyncio
    async def test_overwrite_replaces_existing(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        out = tmp_path / "out"
        # Pre-populate the destination so we can verify overwrite
        (out / "garden" / "idea").mkdir(parents=True)
        (out / "garden" / "idea" / "a.md").write_text("STALE")

        ctx = _make_context(
            vault,
            credentials={"output_vault_path": str(out)},
            input_data={"overwrite": True},
        )
        execute = _load_plugin()
        result = await execute(ctx)

        assert result["written"] == 3
        assert "Body A" in (out / "garden" / "idea" / "a.md").read_text()

    @pytest.mark.asyncio
    async def test_input_data_overrides_credentials_path(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        out = tmp_path / "override-out"
        ctx = _make_context(
            vault,
            credentials={"output_vault_path": str(tmp_path / "default-out")},
            input_data={"output_vault_path": str(out)},
        )
        execute = _load_plugin()
        await execute(ctx)
        assert out.exists()
        assert not (tmp_path / "default-out").exists()

    @pytest.mark.asyncio
    async def test_subdirs_filter(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        out = tmp_path / "out"
        ctx = _make_context(
            vault,
            credentials={"output_vault_path": str(out)},
            input_data={"subdirs": ["garden"]},
        )
        execute = _load_plugin()
        result = await execute(ctx)
        assert result["written"] == 2  # only garden notes, not seeds
        assert (out / "garden" / "idea" / "a.md").exists()
        assert not (out / "seeds").exists()

    @pytest.mark.asyncio
    async def test_missing_output_path_returns_error(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        ctx = _make_context(vault)
        execute = _load_plugin()
        result = await execute(ctx)
        assert result["written"] == 0
        assert "error" in result
