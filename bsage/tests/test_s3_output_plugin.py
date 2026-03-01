"""Tests for the s3-output plugin."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch


def _load_plugin():
    """Import the plugin module and return the execute function and module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("s3_output", "plugins/s3-output/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # boto3 is imported at module-level inside execute(), so we need it available
    mock_boto3 = MagicMock()
    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        spec.loader.exec_module(mod)
    return mod.execute, mock_boto3


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


async def test_execute_uploads_file(tmp_path) -> None:
    mock_boto3 = MagicMock()
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        execute_fn, _ = _load_plugin()

        vault = tmp_path / "vault"
        vault.mkdir()
        source = vault / "seeds" / "note.md"
        source.parent.mkdir(parents=True)
        source.write_text("file content")

        ctx = _make_context(
            input_data={"path": str(source)},
            credentials={
                "aws_access_key_id": "AKID",
                "aws_secret_access_key": "SECRET",
                "bucket": "my-bucket",
                "prefix": "bsage/",
                "region": "us-west-2",
            },
            config={"vault_path": str(vault)},
        )

        result = await execute_fn(ctx)

    assert result["synced"] is True
    assert result["bucket"] == "my-bucket"
    assert result["key"] == "bsage/seeds/note.md"
    mock_client.put_object.assert_called_once()
    call_kwargs = mock_client.put_object.call_args[1]
    assert call_kwargs["Bucket"] == "my-bucket"
    assert call_kwargs["Key"] == "bsage/seeds/note.md"
    assert call_kwargs["ContentType"] == "text/markdown"


async def test_execute_source_not_exists(tmp_path) -> None:
    mock_boto3 = MagicMock()
    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        execute_fn, _ = _load_plugin()

        ctx = _make_context(
            input_data={"path": str(tmp_path / "nonexistent.md")},
            credentials={
                "aws_access_key_id": "AKID",
                "aws_secret_access_key": "SECRET",
                "bucket": "my-bucket",
            },
            config={"vault_path": str(tmp_path)},
        )

        result = await execute_fn(ctx)

    assert result["synced"] is False
    assert "does not exist" in result["error"]


async def test_execute_correct_key_prefix(tmp_path) -> None:
    mock_boto3 = MagicMock()
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        execute_fn, _ = _load_plugin()

        vault = tmp_path / "vault"
        vault.mkdir()
        source = vault / "garden" / "insights" / "weekly.md"
        source.parent.mkdir(parents=True)
        source.write_text("insight content")

        ctx = _make_context(
            input_data={"path": str(source)},
            credentials={
                "aws_access_key_id": "AKID",
                "aws_secret_access_key": "SECRET",
                "bucket": "my-bucket",
                "prefix": "custom-prefix/",
                "region": "eu-west-1",
            },
            config={"vault_path": str(vault)},
        )

        result = await execute_fn(ctx)

    assert result["synced"] is True
    assert result["key"] == "custom-prefix/garden/insights/weekly.md"
    assert result["bucket"] == "my-bucket"
