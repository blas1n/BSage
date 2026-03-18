"""Tests for the slack-input plugin."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
    vault_root: Path | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {"bot_token": "xoxb-test", "channel_id": "C123"}
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    ctx.garden.resolve_plugin_state_path = MagicMock(
        side_effect=lambda plugin_name, subpath="_state.json": (vault_root or Path("/tmp")) / "seeds" / plugin_name / subpath
    )
    ctx.chat = None
    ctx.logger = MagicMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return execute function."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("slack_input", "plugins/slack-input/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


@pytest.mark.asyncio
async def test_execute_missing_credentials() -> None:
    """Test that execute returns error when credentials are missing."""
    execute_fn = _load_plugin()
    ctx = _make_context(credentials={})

    result = await execute_fn(ctx)

    assert result.get("collected") == 0
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_fetches_and_writes_messages(tmp_path) -> None:
    """Test that execute fetches messages and writes to seed."""
    execute_fn = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_response = {
        "ok": True,
        "messages": [
            {
                "type": "message",
                "user": "U123",
                "username": "alice",
                "text": "Hello world",
                "ts": "1700000000.000100",
            },
        ],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["collected"] == 1
    ctx.garden.write_seed.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_handles_api_error() -> None:
    """Test that execute handles API errors gracefully."""
    execute_fn = _load_plugin()
    ctx = _make_context()

    api_response = {"ok": False, "error": "channel_not_found"}

    mock_resp = MagicMock()
    mock_resp.json.return_value = api_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result.get("collected") == 0
    assert "error" in result
