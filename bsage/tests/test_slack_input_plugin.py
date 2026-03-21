"""Tests for the slack-input plugin."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bsage.tests.conftest import make_httpx_mock, make_plugin_context

_DEFAULT_CREDS = {"bot_token": "xoxb-test", "channel_id": "C123"}


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
    vault_root: Path | None = None,
) -> MagicMock:
    return make_plugin_context(
        input_data=input_data,
        credentials=credentials or _DEFAULT_CREDS,
        vault_root=vault_root,
        include_state_path=True,
    )


def _load_plugin():
    """Import the plugin module and return (execute, notify, module)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("slack_input", "plugins/slack-input/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute, mod.execute.__notify__, mod


def _mock_response(json_data):
    """Build a mock HTTP response."""
    resp = MagicMock()
    resp.status_code = 200
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
    """Test that execute fetches messages and writes to seed."""
    execute_fn, _, _ = _load_plugin()
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

    mock_resp = _mock_response(api_response)

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result["collected"] == 1
    ctx.garden.write_seed.assert_awaited_once()
    call_args = ctx.garden.write_seed.call_args
    assert call_args[0][0] == "slack"
    messages = call_args[0][1]["messages"]
    assert messages[0]["text"] == "Hello world"


@pytest.mark.asyncio
async def test_execute_handles_api_error() -> None:
    """Test that execute handles API errors gracefully."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context()

    mock_resp = _mock_response({"ok": False, "error": "channel_not_found"})

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert result["error"] == "channel_not_found"


@pytest.mark.asyncio
async def test_execute_no_messages(tmp_path: Path) -> None:
    """Test that execute handles empty message list."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    mock_resp = _mock_response({"ok": True, "messages": []})

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result["collected"] == 0
    ctx.garden.write_seed.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_skips_subtypes(tmp_path: Path) -> None:
    """Test that execute skips messages with subtypes (bot, join, etc.)."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_response = {
        "ok": True,
        "messages": [
            {
                "type": "message",
                "subtype": "bot_message",
                "text": "Bot says hi",
                "ts": "1700000000.000100",
            },
            {
                "type": "message",
                "user": "U999",
                "text": "Real user message",
                "ts": "1700000000.000200",
            },
        ],
    }

    mock_resp = _mock_response(api_response)

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result["collected"] == 1


@pytest.mark.asyncio
async def test_notify_sends_message() -> None:
    """Test that notify sends a message to Slack channel."""
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(input_data={"message": "Hello from BSage"})

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "ts": "1700000001.000100"}

    with make_httpx_mock(post_response=mock_resp) as mock_client:
        result = await notify_fn(ctx)

    assert result["sent"] is True
    assert result["ts"] == "1700000001.000100"
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_missing_message() -> None:
    """Test that notify returns error when no message is provided."""
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(input_data={"other": "data"})

    result = await notify_fn(ctx)

    assert result["sent"] is False
    assert "no message" in result["reason"]


@pytest.mark.asyncio
async def test_notify_missing_credentials() -> None:
    """Test that notify returns error when credentials are missing."""
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(
        input_data={"message": "hello"},
        credentials={"bot_token": "", "channel_id": ""},
    )

    result = await notify_fn(ctx)

    assert result["sent"] is False
    assert "missing" in result["reason"]


@pytest.mark.asyncio
async def test_execute_saves_cursor_state(tmp_path: Path) -> None:
    """Test that execute persists latest timestamp to state file."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_response = {
        "ok": True,
        "messages": [
            {
                "type": "message",
                "user": "U123",
                "text": "Hello",
                "ts": "1700000000.000200",
            },
        ],
    }

    mock_resp = _mock_response(api_response)

    with make_httpx_mock(get_response=mock_resp):
        await execute_fn(ctx)

    state_file = tmp_path / "seeds" / "slack-input" / "_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["cursor"] == "1700000000.000200"


@pytest.mark.asyncio
async def test_execute_uses_existing_cursor(tmp_path: Path) -> None:
    """Test that execute passes saved cursor as 'oldest' param for forward polling."""
    execute_fn, _, _ = _load_plugin()

    # Pre-populate state
    state_dir = tmp_path / "seeds" / "slack-input"
    state_dir.mkdir(parents=True)
    (state_dir / "_state.json").write_text(json.dumps({"cursor": "1700000000.000100"}))

    ctx = _make_context(vault_root=tmp_path)

    mock_resp = _mock_response({"ok": True, "messages": []})

    with make_httpx_mock(get_response=mock_resp) as mock_client:
        await execute_fn(ctx)

    # Verify cursor was passed as 'oldest' param (forward polling)
    call_args = mock_client.get.call_args
    assert call_args[1]["params"]["oldest"] == "1700000000.000100"


@pytest.mark.asyncio
async def test_execute_corrupted_state_file(tmp_path: Path) -> None:
    """Test that corrupted state file is handled gracefully."""
    execute_fn, _, _ = _load_plugin()

    # Write corrupted JSON to state file
    state_dir = tmp_path / "seeds" / "slack-input"
    state_dir.mkdir(parents=True)
    (state_dir / "_state.json").write_text("{broken json!!")

    ctx = _make_context(vault_root=tmp_path)

    mock_resp = _mock_response(
        {
            "ok": True,
            "messages": [
                {"ts": "1700000000.000100", "text": "hello", "user": "U123", "type": "message"},
            ],
        }
    )

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    # Should not crash — treats corrupted state as fresh start
    assert result["collected"] == 1


@pytest.mark.asyncio
async def test_execute_rejects_invalid_channel_id() -> None:
    """Test that execute rejects channel_id not starting with C/G/D."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(credentials={"bot_token": "xoxb-test", "channel_id": "INVALID"})

    result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert "invalid" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_execute_handles_http_status_error() -> None:
    """Test that execute handles HTTP status errors (e.g. 500)."""
    import httpx

    execute_fn, _, _ = _load_plugin()
    ctx = _make_context()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
    )

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_unicode_emoji_messages(tmp_path: Path) -> None:
    """Test that messages with unicode, emoji, and special chars are handled correctly."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_response = {
        "ok": True,
        "messages": [
            {"type": "message", "user": "U1", "text": "Hello 🌍🎉!", "ts": "1000.1"},
            {"type": "message", "user": "U2", "text": "한국어 테스트", "ts": "1000.2"},
            {"type": "message", "user": "U3", "text": "café résumé naïve", "ts": "1000.3"},
        ],
    }

    resp = _mock_response(api_response)

    with make_httpx_mock(get_response=resp):
        result = await execute_fn(ctx)

    assert result["collected"] == 3
    ctx.garden.write_seed.assert_awaited_once()
    seed_data = ctx.garden.write_seed.call_args[0][1]
    texts = [m["text"] for m in seed_data["messages"]]
    assert "Hello 🌍🎉!" in texts
    assert "한국어 테스트" in texts
    assert "café résumé naïve" in texts


@pytest.mark.asyncio
async def test_execute_rejects_invalid_channel_id_format() -> None:
    """Test that execute rejects channel IDs that don't match Slack format."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(credentials={"bot_token": "xoxb-test", "channel_id": "invalid123"})

    result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert "invalid" in result.get("error", "").lower()
