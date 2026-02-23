"""Tests for bsage.garden.vault — Vault path management and file access."""

from pathlib import Path

import pytest

from bsage.core.exceptions import VaultPathError
from bsage.garden.vault import Vault


class TestVaultEnsureDirs:
    """Test Vault.ensure_dirs creates required subdirectories."""

    def test_ensure_dirs_creates_subdirectories(self, tmp_path: Path) -> None:
        """ensure_dirs should create seeds/, garden/, actions/ under vault_path."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()

        assert (tmp_path / "seeds").is_dir()
        assert (tmp_path / "garden").is_dir()
        assert (tmp_path / "actions").is_dir()

    def test_ensure_dirs_idempotent(self, tmp_path: Path) -> None:
        """Calling ensure_dirs multiple times should not raise."""
        vault = Vault(tmp_path)
        vault.ensure_dirs()
        vault.ensure_dirs()

        assert (tmp_path / "seeds").is_dir()
        assert (tmp_path / "garden").is_dir()
        assert (tmp_path / "actions").is_dir()


class TestVaultResolvePath:
    """Test Vault.resolve_path validates paths within the vault boundary."""

    def test_resolve_path_returns_valid_path(self, tmp_path: Path) -> None:
        """resolve_path should return a valid path within the vault."""
        vault = Vault(tmp_path)
        result = vault.resolve_path("seeds/calendar/2026-02-21.md")

        expected = tmp_path.resolve() / "seeds" / "calendar" / "2026-02-21.md"
        assert result == expected

    def test_resolve_path_blocks_traversal(self, tmp_path: Path) -> None:
        """resolve_path should raise VaultPathError for directory traversal."""
        vault = Vault(tmp_path)

        with pytest.raises(VaultPathError, match="traversal"):
            vault.resolve_path("../../etc/passwd")

    def test_resolve_path_blocks_absolute_path(self, tmp_path: Path) -> None:
        """resolve_path should raise VaultPathError for absolute paths outside vault."""
        vault = Vault(tmp_path)

        with pytest.raises(VaultPathError, match="traversal"):
            vault.resolve_path("/etc/passwd")


class TestVaultReadNotes:
    """Test Vault.read_notes returns markdown files sorted by name."""

    @pytest.mark.asyncio
    async def test_read_notes_returns_md_files_sorted(self, tmp_path: Path) -> None:
        """read_notes should return only .md files, sorted by name."""
        vault = Vault(tmp_path)
        notes_dir = tmp_path / "garden" / "ideas"
        notes_dir.mkdir(parents=True)

        (notes_dir / "beta.md").write_text("# Beta")
        (notes_dir / "alpha.md").write_text("# Alpha")
        (notes_dir / "gamma.md").write_text("# Gamma")
        (notes_dir / "readme.txt").write_text("not a note")

        result = await vault.read_notes("garden/ideas")

        assert len(result) == 3
        assert result[0].name == "alpha.md"
        assert result[1].name == "beta.md"
        assert result[2].name == "gamma.md"

    @pytest.mark.asyncio
    async def test_read_notes_empty_dir(self, tmp_path: Path) -> None:
        """read_notes should return an empty list for an empty directory."""
        vault = Vault(tmp_path)
        empty_dir = tmp_path / "garden" / "empty"
        empty_dir.mkdir(parents=True)

        result = await vault.read_notes("garden/empty")

        assert result == []

    @pytest.mark.asyncio
    async def test_read_notes_nonexistent_dir(self, tmp_path: Path) -> None:
        """read_notes should return an empty list for a nonexistent directory."""
        vault = Vault(tmp_path)

        result = await vault.read_notes("garden/nonexistent")

        assert result == []


class TestVaultReadNoteContent:
    """Test Vault.read_note_content reads file content asynchronously."""

    @pytest.mark.asyncio
    async def test_read_note_content_returns_text(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path)
        note = tmp_path / "test.md"
        note.write_text("# Hello\nContent here", encoding="utf-8")

        content = await vault.read_note_content(note)

        assert content == "# Hello\nContent here"

    @pytest.mark.asyncio
    async def test_read_note_content_blocks_traversal(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path)
        outside = tmp_path.parent / "secret.md"
        outside.write_text("secret", encoding="utf-8")

        with pytest.raises(VaultPathError, match="traversal"):
            await vault.read_note_content(outside)

    @pytest.mark.asyncio
    async def test_read_note_content_raises_on_missing_file(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path)
        missing = tmp_path / "nonexistent.md"

        with pytest.raises(OSError):
            await vault.read_note_content(missing)
