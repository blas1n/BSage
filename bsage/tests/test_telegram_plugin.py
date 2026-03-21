"""Tests for the telegram-input plugin."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.tests.conftest import make_httpx_mock, make_plugin_context

_DEFAULT_CREDS = {"bot_token": "tok123", "chat_id": "456"}


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
    vault_root: Path | None = None,
) -> MagicMock:
    ctx = make_plugin_context(
        input_data=input_data,
        credentials=credentials or _DEFAULT_CREDS,
        vault_root=vault_root,
        include_chat=True,
        include_state_path=True,
    )
    ctx.chat.chat = AsyncMock(return_value="ChatBridge reply")
    return ctx


def _load_plugin():
    """Import the plugin module and return (execute, notify) functions."""
    import importlib
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "telegram_input", "plugins/telegram-input/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute, mod.execute.__notify__, mod


def _telegram_update(update_id: int, text: str, chat_id: int = 123) -> dict:
    """Build a minimal Telegram Update object."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id * 10,
            "chat": {"id": chat_id},
            "from": {"id": 999, "username": "testuser"},
            "text": text,
            "date": 1700000000,
        },
    }


def _mock_response(json_data):
    """Build a mock HTTP response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data
    return resp


# ── execute() tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_polls_and_writes_seeds(tmp_path) -> None:
    execute_fn, _, mod = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_response = {
        "ok": True,
        "result": [
            _telegram_update(101, "hello"),
            _telegram_update(102, "world"),
        ],
    }

    mock_resp = _mock_response(api_response)

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result == {"collected": 2}
    ctx.garden.write_seed.assert_awaited_once()
    call_args = ctx.garden.write_seed.call_args
    assert call_args[0][0] == "telegram"
    messages = call_args[0][1]["messages"]
    assert len(messages) == 2
    assert messages[0]["text"] == "hello"
    assert messages[1]["text"] == "world"


@pytest.mark.asyncio
async def test_execute_saves_offset(tmp_path) -> None:
    execute_fn, _, mod = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_response = {
        "ok": True,
        "result": [_telegram_update(200, "test")],
    }

    mock_resp = _mock_response(api_response)

    with make_httpx_mock(get_response=mock_resp):
        await execute_fn(ctx)

    state_file = tmp_path / "seeds" / "telegram-input" / "_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["last_update_id"] == 200


@pytest.mark.asyncio
async def test_execute_uses_existing_offset(tmp_path) -> None:
    execute_fn, _, mod = _load_plugin()

    # Pre-populate state file
    state_dir = tmp_path / "seeds" / "telegram-input"
    state_dir.mkdir(parents=True)
    (state_dir / "_state.json").write_text(json.dumps({"last_update_id": 99}))

    ctx = _make_context(vault_root=tmp_path)

    api_response = {"ok": True, "result": []}

    mock_resp = _mock_response(api_response)

    with make_httpx_mock(get_response=mock_resp) as mock_client:
        result = await execute_fn(ctx)

    assert result == {"collected": 0}
    # Verify offset was passed
    call_args = mock_client.get.call_args
    assert call_args[1]["params"]["offset"] == 100  # last_update_id + 1


@pytest.mark.asyncio
async def test_execute_no_updates(tmp_path) -> None:
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    mock_resp = _mock_response({"ok": True, "result": []})

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result == {"collected": 0}
    ctx.garden.write_seed.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_missing_bot_token(tmp_path) -> None:
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(credentials={"bot_token": "", "chat_id": "456"}, vault_root=tmp_path)
    result = await execute_fn(ctx)
    assert result == {"collected": 0, "error": "missing bot_token"}


@pytest.mark.asyncio
async def test_execute_skips_non_message_updates(tmp_path) -> None:
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_response = {
        "ok": True,
        "result": [
            {"update_id": 300, "callback_query": {"id": "abc"}},  # Not a message
            _telegram_update(301, "real message"),
        ],
    }

    mock_resp = _mock_response(api_response)

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result == {"collected": 1}


# ── auto-reply tests (via context.chat / ChatBridge) ─────────────────


@pytest.mark.asyncio
async def test_execute_calls_chat_bridge(tmp_path) -> None:
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    api_response = {
        "ok": True,
        "result": [_telegram_update(500, "Hello bot")],
    }

    mock_resp = _mock_response(api_response)

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result == {"collected": 1}
    ctx.chat.chat.assert_awaited_once_with(message="Hello bot")
    ctx.logger.info.assert_any_call("auto_reply_sent", length=len("ChatBridge reply"))


@pytest.mark.asyncio
async def test_execute_no_reply_when_chat_is_none(tmp_path) -> None:
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)
    ctx.chat = None

    api_response = {
        "ok": True,
        "result": [_telegram_update(501, "Hello")],
    }

    mock_resp = _mock_response(api_response)

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result == {"collected": 1}
    # Should not crash when chat is None


# ── _parse_update() tests ────────────────────────────────────────────


def test_parse_update_text_message() -> None:
    _, _, mod = _load_plugin()
    update = _telegram_update(1, "hello", chat_id=555)
    parsed = mod._parse_update(update)
    assert parsed["text"] == "hello"
    assert parsed["chat_id"] == 555
    assert parsed["from_username"] == "testuser"
    assert parsed["update_id"] == 1


def test_parse_update_edited_message() -> None:
    _, _, mod = _load_plugin()
    update = {
        "update_id": 2,
        "edited_message": {
            "message_id": 20,
            "chat": {"id": 777},
            "from": {"id": 1, "username": "editor"},
            "text": "edited text",
            "date": 1700000000,
        },
    }
    parsed = mod._parse_update(update)
    assert parsed["text"] == "edited text"
    assert parsed["chat_id"] == 777


def test_parse_update_no_message() -> None:
    _, _, mod = _load_plugin()
    update = {"update_id": 3, "callback_query": {"id": "xyz"}}
    assert mod._parse_update(update) is None


# ── notify() tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_sends_message() -> None:
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(
        input_data={"message": "Hello from BSage"},
        credentials={"bot_token": "tok123", "chat_id": "456"},
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"ok": True, "result": {"message_id": 1}})

    with make_httpx_mock(post_response=mock_response) as mock_client:
        result = await notify_fn(ctx)

    assert result["sent"] is True
    assert result["chat_id"] == "456"
    mock_client.post.assert_awaited_once()
    call_args = mock_client.post.call_args
    assert call_args[1]["json"]["text"] == "Hello from BSage"


@pytest.mark.asyncio
async def test_notify_missing_message() -> None:
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(input_data={"other": "data"})
    result = await notify_fn(ctx)
    assert result == {"sent": False, "reason": "no message provided"}


@pytest.mark.asyncio
async def test_notify_empty_input_data() -> None:
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(input_data=None)
    result = await notify_fn(ctx)
    assert result == {"sent": False, "reason": "no message provided"}


@pytest.mark.asyncio
async def test_notify_missing_credentials() -> None:
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(
        input_data={"message": "hi"},
        credentials={"bot_token": "", "chat_id": ""},
    )
    result = await notify_fn(ctx)
    assert result == {"sent": False, "reason": "missing bot_token or chat_id"}


@pytest.mark.asyncio
async def test_notify_http_error_raises() -> None:
    """HTTP errors from Telegram API propagate as-is.

    This is intentional: unlike missing credentials (which return
    ``{"sent": False}``), transport/server errors should surface to the
    caller so the notification router can handle retries or alerting.
    """
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(input_data={"message": "hi"})

    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "403 Forbidden",
            request=MagicMock(),
            response=MagicMock(status_code=403),
        )
    )

    with make_httpx_mock(post_response=mock_response), pytest.raises(httpx.HTTPStatusError):
        await notify_fn(ctx)


@pytest.mark.asyncio
async def test_execute_raises_on_http_status_error(tmp_path) -> None:
    """Test that execute propagates HTTP status errors from Telegram API."""
    import httpx

    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
        )
    )

    with make_httpx_mock(get_response=mock_resp), pytest.raises(httpx.HTTPStatusError):
        await execute_fn(ctx)


@pytest.mark.asyncio
async def test_execute_malformed_json_response(tmp_path) -> None:
    """Test that execute handles malformed JSON response gracefully."""
    execute_fn, _, _ = _load_plugin()
    ctx = _make_context(vault_root=tmp_path)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(side_effect=ValueError("Invalid JSON"))
    mock_resp.status_code = 200

    with make_httpx_mock(get_response=mock_resp):
        result = await execute_fn(ctx)

    assert result["collected"] == 0
    assert result["error"] == "malformed JSON response"


@pytest.mark.asyncio
async def test_notify_api_error_in_body() -> None:
    """Test that notify detects Telegram API error in response body."""
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(input_data={"message": "hi"})

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"ok": False, "description": "Unauthorized"})

    with make_httpx_mock(post_response=mock_resp):
        result = await notify_fn(ctx)

    assert result["sent"] is False
    assert "Unauthorized" in result["reason"]


@pytest.mark.asyncio
async def test_notify_success_checks_ok_field() -> None:
    """Test that notify verifies ok=True in Telegram response."""
    _, notify_fn, _ = _load_plugin()
    ctx = _make_context(input_data={"message": "hi"})

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"ok": True, "result": {"message_id": 123}})

    with make_httpx_mock(post_response=mock_resp):
        result = await notify_fn(ctx)

    assert result["sent"] is True
