"""Tests for the telegram-input plugin."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {"bot_token": "tok123", "chat_id": "456"}
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
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
    return mod.execute, mod.execute.__notify__


# ── execute() tests ───────────────────────────────────────────────────


async def test_execute_writes_seeds() -> None:
    execute_fn, _ = _load_plugin()
    ctx = _make_context(input_data={"messages": ["hello", "world"]})
    result = await execute_fn(ctx)
    assert result == {"collected": 2}
    ctx.garden.write_seed.assert_awaited_once_with("telegram", {"messages": ["hello", "world"]})


async def test_execute_empty_input_data() -> None:
    execute_fn, _ = _load_plugin()
    ctx = _make_context(input_data=None)
    result = await execute_fn(ctx)
    assert result == {"collected": 0}


# ── notify() tests ────────────────────────────────────────────────────


async def test_notify_sends_message() -> None:
    _, notify_fn = _load_plugin()
    ctx = _make_context(
        input_data={"message": "Hello from BSage"},
        credentials={"bot_token": "tok123", "chat_id": "456"},
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await notify_fn(ctx)

    assert result["sent"] is True
    assert result["chat_id"] == "456"
    mock_client.post.assert_awaited_once()
    call_args = mock_client.post.call_args
    assert "bot_token" not in str(call_args)  # token is in URL, not logged
    assert call_args[1]["json"]["text"] == "Hello from BSage"


async def test_notify_missing_message() -> None:
    _, notify_fn = _load_plugin()
    ctx = _make_context(input_data={"other": "data"})
    result = await notify_fn(ctx)
    assert result == {"sent": False, "reason": "no message provided"}


async def test_notify_empty_input_data() -> None:
    _, notify_fn = _load_plugin()
    ctx = _make_context(input_data=None)
    result = await notify_fn(ctx)
    assert result == {"sent": False, "reason": "no message provided"}


async def test_notify_missing_credentials() -> None:
    _, notify_fn = _load_plugin()
    ctx = _make_context(
        input_data={"message": "hi"},
        credentials={"bot_token": "", "chat_id": ""},
    )
    result = await notify_fn(ctx)
    assert result == {"sent": False, "reason": "missing bot_token or chat_id"}


async def test_notify_http_error_raises() -> None:
    _, notify_fn = _load_plugin()
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

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(httpx.HTTPStatusError):
            await notify_fn(ctx)
