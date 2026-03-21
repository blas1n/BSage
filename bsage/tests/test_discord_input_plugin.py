"""Tests for the discord-input plugin."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bsage.tests.conftest import make_plugin_context

_DEFAULT_CREDS = {"bot_token": "dsc_token_123", "channel_id": "123456789"}


def _make_context(
    vault_root: Path | None = None,
    credentials: dict | None = None,
) -> MagicMock:
    return make_plugin_context(
        credentials=credentials or _DEFAULT_CREDS,
        vault_root=vault_root,
        include_state_path=True,
    )


def _load_plugin():
    """Import the plugin module and return (execute, notify, module)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "discord_input", "plugins/discord-input/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute, mod.execute.__notify__, mod


def _discord_message(
    msg_id: str, content: str, timestamp: str = "2024-01-15T10:30:00+00:00"
) -> dict:
    """Build a minimal Discord message object."""
    return {
        "id": msg_id,
        "content": content,
        "author": {"id": "user_1", "username": "testuser"},
        "timestamp": timestamp,
    }


@pytest.mark.asyncio
async def test_execute_missing_credentials() -> None:
    """Test that execute returns error when credentials are missing."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(credentials={"bot_token": "", "channel_id": ""})

    result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_fetches_and_writes_messages(tmp_path: Path) -> None:
    """Test that execute fetches messages, parses, and writes to seed."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_messages = [
        _discord_message("msg_2", "world", "2024-01-15T10:31:00+00:00"),
        _discord_message("msg_1", "hello", "2024-01-15T10:30:00+00:00"),
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_messages

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["collected"] == 2
    ctx.garden.write_seed.assert_awaited_once()
    call_args = ctx.garden.write_seed.call_args
    assert call_args[0][0] == "discord"
    messages = call_args[0][1]["messages"]
    assert len(messages) == 2
    # reversed order — oldest first
    assert messages[0]["content"] == "hello"
    assert messages[1]["content"] == "world"


@pytest.mark.asyncio
async def test_execute_handles_api_error() -> None:
    """Test that execute handles Discord API errors gracefully."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"code": 50001, "message": "Missing Access"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_no_new_messages(tmp_path: Path) -> None:
    """Test that execute handles empty message list."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = []

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["collected"] == 0
    ctx.garden.write_seed.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_sends_message() -> None:
    """Test that notify sends a message to Discord channel."""
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"message": "Hello from BSage"}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"id": "msg_99"}'
    mock_resp.json.return_value = {"id": "msg_99"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await notify_fn(ctx)

    assert result["sent"] is True
    assert result["message_id"] == "msg_99"
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_saves_timestamp_state(tmp_path: Path) -> None:
    """Test that execute persists highest timestamp to state file."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_messages = [
        _discord_message("msg_1", "hello", "2024-01-15T10:30:00+00:00"),
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_messages

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        await execute_fn(ctx)

    state_file = tmp_path / "seeds" / "discord-input" / "_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["last_message_timestamp"] > 0


@pytest.mark.asyncio
async def test_execute_uses_existing_timestamp(tmp_path: Path) -> None:
    """Test that execute filters messages using saved timestamp."""
    execute_fn, _, _ = _load_plugin()

    # Pre-populate state: timestamp after msg_1 (10:30:00) but before msg_2 (10:31:00)
    state_dir = tmp_path / "seeds" / "discord-input"
    state_dir.mkdir(parents=True)
    # 2024-01-15T10:30:00+00:00 = 1705314600000 ms, set state to 30s after
    (state_dir / "_state.json").write_text(json.dumps({"last_message_timestamp": 1705314630000}))

    ctx = _make_context(vault_root=tmp_path)

    api_messages = [
        _discord_message("msg_2", "new", "2024-01-15T10:31:00+00:00"),
        _discord_message("msg_1", "old", "2024-01-15T10:30:00+00:00"),
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_messages

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    # Only msg_2 should be collected (msg_1 timestamp < saved timestamp)
    assert result["collected"] == 1


@pytest.mark.asyncio
async def test_execute_rejects_invalid_channel_id() -> None:
    """Test that execute rejects non-numeric channel_id."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(credentials={"bot_token": "tok", "channel_id": "../../etc/passwd"})

    result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert "invalid" in result.get("error", "").lower()
