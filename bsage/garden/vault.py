"""Vault — secure path management and file access for the 2nd Brain."""

from pathlib import Path

import structlog

from bsage.core.exceptions import VaultPathError

logger = structlog.get_logger(__name__)

VAULT_SUBDIRS = ("seeds", "garden", "actions")


class Vault:
    """Manages the on-disk vault directory structure and enforces path boundaries.

    The vault contains three top-level directories:
    - seeds/   — raw data collected by InputSkills
    - garden/  — processed knowledge notes
    - actions/ — agent action logs
    """

    def __init__(self, vault_path: Path) -> None:
        self._root = vault_path.resolve()

    @property
    def root(self) -> Path:
        """Return the resolved vault root path."""
        return self._root

    def ensure_dirs(self) -> None:
        """Create seeds/, garden/, actions/ subdirectories if they don't exist."""
        for subdir in VAULT_SUBDIRS:
            path = self._root / subdir
            path.mkdir(parents=True, exist_ok=True)
            logger.debug("vault_dir_ensured", path=str(path))

    def resolve_path(self, subpath: str) -> Path:
        """Resolve a subpath within the vault, blocking directory traversal.

        Args:
            subpath: Relative path within the vault (e.g. "seeds/calendar/2026-02-21.md").

        Returns:
            Resolved absolute Path within the vault.

        Raises:
            VaultPathError: If the resolved path escapes the vault boundary.
        """
        resolved = (self._root / subpath).resolve()
        if not resolved.is_relative_to(self._root):
            logger.warning(
                "vault_path_traversal_blocked",
                subpath=subpath,
                resolved=str(resolved),
            )
            raise VaultPathError(f"Path traversal detected: '{subpath}' resolves outside the vault")
        return resolved

    def read_notes(self, subdir: str) -> list[Path]:
        """Return sorted list of .md files in a vault subdirectory.

        Args:
            subdir: Relative directory path within the vault (e.g. "garden/ideas").

        Returns:
            List of Path objects for .md files, sorted by filename.
            Returns an empty list if the directory doesn't exist.
        """
        target = self.resolve_path(subdir)
        if not target.is_dir():
            logger.debug("vault_read_notes_no_dir", subdir=subdir)
            return []

        md_files = sorted(target.glob("*.md"), key=lambda p: p.name)
        logger.debug("vault_read_notes", subdir=subdir, count=len(md_files))
        return md_files
