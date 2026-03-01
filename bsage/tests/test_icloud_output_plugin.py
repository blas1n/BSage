"""Tests for the icloud-output plugin."""

from unittest.mock import AsyncMock, MagicMock


def _load_plugin():
    """Import the plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "icloud_output", "plugins/icloud-output/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
    config: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {}
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    ctx.garden.write_action = AsyncMock()
    ctx.config = config or {}
    return ctx


# ── execute() tests ───────────────────────────────────────────────────


async def test_execute_copies_file(tmp_path) -> None:
    execute_fn = _load_plugin()

    # Set up vault with a source file
    vault = tmp_path / "vault"
    vault.mkdir()
    source = vault / "seeds" / "note.md"
    source.parent.mkdir(parents=True)
    source.write_text("icloud content")

    # Set up iCloud directory
    icloud_dir = tmp_path / "icloud_drive"
    icloud_dir.mkdir()

    ctx = _make_context(
        input_data={"path": str(source)},
        credentials={"icloud_path": str(icloud_dir)},
        config={"vault_path": str(vault)},
    )

    result = await execute_fn(ctx)

    assert result["synced"] is True
    dest = icloud_dir / "seeds" / "note.md"
    assert dest.exists()
    assert dest.read_text() == "icloud content"


async def test_execute_icloud_path_missing(tmp_path) -> None:
    execute_fn = _load_plugin()

    vault = tmp_path / "vault"
    vault.mkdir()
    source = vault / "note.md"
    source.write_text("content")

    # Point to a non-existent iCloud directory
    missing_icloud = tmp_path / "nonexistent_icloud"

    ctx = _make_context(
        input_data={"path": str(source)},
        credentials={"icloud_path": str(missing_icloud)},
        config={"vault_path": str(vault)},
    )

    result = await execute_fn(ctx)

    assert result["synced"] is False
    assert "does not exist" in result["error"]


async def test_execute_source_not_exists(tmp_path) -> None:
    execute_fn = _load_plugin()

    icloud_dir = tmp_path / "icloud_drive"
    icloud_dir.mkdir()

    ctx = _make_context(
        input_data={"path": str(tmp_path / "nonexistent.md")},
        credentials={"icloud_path": str(icloud_dir)},
        config={"vault_path": str(tmp_path)},
    )

    result = await execute_fn(ctx)

    assert result["synced"] is False
    assert "does not exist" in result["error"]
