"""Tests for the discord-input plugin."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bsage.tests.conftest import make_httpx_mock, make_plugin_context

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


def _mock_get_response(json_data, status_code=200):
    """Build a mock HTTP response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data
    return resp


@pytest.mark.asyncio
async def test_execute_missing_credentials() -> None:
    """Test that execute returns error when credentials are missing."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(credentials={"bot_token": "", "channel_id": ""})

    result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert "missing" in result["error"].lower()


@pytest.mark.asyncio
async def test_execute_fetches_and_writes_messages(tmp_path: Path) -> None:
    """Test that execute fetches messages, parses, and writes to seed."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_messages = [
        _discord_message("msg_2", "world", "2024-01-15T10:31:00+00:00"),
        _discord_message("msg_1", "hello", "2024-01-15T10:30:00+00:00"),
    ]

    mock_resp = _mock_get_response(api_messages)

    with make_httpx_mock(get_response=mock_resp):
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

    mock_resp = _mock_get_response({"code": 50001, "message": "Missing Access"})

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert result["error"] == "Missing Access"


@pytest.mark.asyncio
async def test_execute_handles_http_status_error() -> None:
    """Test that execute handles HTTP status errors (e.g. 401, 500)."""
    import httpx

    execute_fn, _, _ = _load_plugin()
    ctx = _make_context()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
        )
    )

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_no_new_messages(tmp_path: Path) -> None:
    """Test that execute handles empty message list."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    mock_resp = _mock_get_response([])

    with make_httpx_mock(get_response=mock_resp):
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

    with make_httpx_mock(post_response=mock_resp) as mock_client:
        result = await notify_fn(ctx)

    assert result["sent"] is True
    assert result["message_id"] == "msg_99"
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_missing_message() -> None:
    """Test that notify returns error when no message is provided."""
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"other": "data"}

    result = await notify_fn(ctx)

    assert result["sent"] is False
    assert "no message" in result["reason"]


@pytest.mark.asyncio
async def test_notify_missing_credentials() -> None:
    """Test that notify returns error when credentials are missing."""
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(credentials={"bot_token": "", "channel_id": ""})
    ctx.input_data = {"message": "hello"}

    result = await notify_fn(ctx)

    assert result["sent"] is False
    assert "missing" in result["reason"]


@pytest.mark.asyncio
async def test_execute_saves_timestamp_state(tmp_path: Path) -> None:
    """Test that execute persists highest timestamp to state file."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_messages = [
        _discord_message("msg_1", "hello", "2024-01-15T10:30:00+00:00"),
    ]

    mock_resp = _mock_get_response(api_messages)

    with make_httpx_mock(get_response=mock_resp):
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

    mock_resp = _mock_get_response(api_messages)

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    # Only msg_2 should be collected (msg_1 timestamp < saved timestamp)
    assert result["collected"] == 1


@pytest.mark.asyncio
async def test_execute_corrupted_state_file(tmp_path: Path) -> None:
    """Test that corrupted state file is handled gracefully."""
    execute_fn, _, _ = _load_plugin()

    # Write corrupted JSON to state file
    state_dir = tmp_path / "seeds" / "discord-input"
    state_dir.mkdir(parents=True)
    (state_dir / "_state.json").write_text("not valid json{{{")

    ctx = _make_context(vault_root=tmp_path)

    api_messages = [_discord_message("msg_1", "hello", "2024-01-15T10:30:00+00:00")]
    mock_resp = _mock_get_response(api_messages)

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    # Should not crash — treats corrupted state as fresh start
    assert result["collected"] == 1


@pytest.mark.asyncio
async def test_execute_rejects_invalid_channel_id() -> None:
    """Test that execute rejects non-numeric channel_id."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(credentials={"bot_token": "tok", "channel_id": "../../etc/passwd"})

    result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert "invalid" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_execute_unicode_emoji_messages(tmp_path: Path) -> None:
    """Test that messages containing unicode, emoji, and RTL text are handled correctly."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    messages = [
        _discord_message("1", "Hello 🌍🎉 world!"),
        _discord_message("2", "한국어 메시지 테스트", "2024-01-15T10:31:00+00:00"),
        _discord_message("3", "مرحبا بالعالم", "2024-01-15T10:32:00+00:00"),  # Arabic RTL
        _discord_message("4", "café résumé naïve", "2024-01-15T10:33:00+00:00"),
    ]

    resp = _mock_get_response(messages)

    with make_httpx_mock(get_response=resp):
        result = await execute_fn(ctx)

    assert result["collected"] == 4
    ctx.garden.write_seed.assert_awaited_once()
    seed_data = ctx.garden.write_seed.call_args[0][1]
    contents = [m["content"] for m in seed_data["messages"]]
    assert "Hello 🌍🎉 world!" in contents
    assert "한국어 메시지 테스트" in contents
    assert "مرحبا بالعالم" in contents
    assert "café résumé naïve" in contents
