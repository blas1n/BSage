"""Tests for the local-output plugin."""

from unittest.mock import AsyncMock, MagicMock


def _load_plugin():
    """Import the plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("local_output", "plugins/local-output/plugin.py")
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
    source.write_text("hello world")

    # Set up target directory
    target = tmp_path / "backup"
    target.mkdir()

    ctx = _make_context(
        input_data={"path": str(source)},
        credentials={"target_dir": str(target)},
        config={"vault_path": str(vault)},
    )

    result = await execute_fn(ctx)

    assert result["synced"] is True
    dest = target / "seeds" / "note.md"
    assert dest.exists()
    assert dest.read_text() == "hello world"


async def test_execute_source_not_exists(tmp_path) -> None:
    execute_fn = _load_plugin()

    target = tmp_path / "backup"
    target.mkdir()

    ctx = _make_context(
        input_data={"path": str(tmp_path / "nonexistent.md")},
        credentials={"target_dir": str(target)},
        config={"vault_path": str(tmp_path)},
    )

    result = await execute_fn(ctx)

    assert result["synced"] is False
    assert "does not exist" in result["error"]


async def test_execute_non_absolute_target(tmp_path) -> None:
    execute_fn = _load_plugin()

    vault = tmp_path / "vault"
    vault.mkdir()
    source = vault / "note.md"
    source.write_text("content")

    ctx = _make_context(
        input_data={"path": str(source)},
        credentials={"target_dir": "relative/path"},
        config={"vault_path": str(vault)},
    )

    result = await execute_fn(ctx)

    assert result["synced"] is False
    assert "absolute" in result["error"]


async def test_execute_preserves_structure(tmp_path) -> None:
    execute_fn = _load_plugin()

    # Set up vault with nested subdirectory structure
    vault = tmp_path / "vault"
    vault.mkdir()
    deep_source = vault / "garden" / "ideas" / "deep-thought.md"
    deep_source.parent.mkdir(parents=True)
    deep_source.write_text("deep thought content")

    target = tmp_path / "backup"
    target.mkdir()

    ctx = _make_context(
        input_data={"path": str(deep_source)},
        credentials={"target_dir": str(target)},
        config={"vault_path": str(vault)},
    )

    result = await execute_fn(ctx)

    assert result["synced"] is True
    dest = target / "garden" / "ideas" / "deep-thought.md"
    assert dest.exists()
    assert dest.read_text() == "deep thought content"
