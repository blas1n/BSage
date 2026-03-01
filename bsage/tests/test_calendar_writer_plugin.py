"""Tests for the calendar-writer plugin."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {
        "google_api_key": "fake-token",
        "calendar_id": "primary",
    }
    ctx.garden = AsyncMock()
    ctx.garden.write_action = AsyncMock()
    ctx.logger = MagicMock()
    return ctx


def _load_plugin():
    """Import the calendar-writer plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "calendar_writer", "plugins/calendar-writer/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


# ── test_execute_creates_event ───────────────────────────────────────


async def test_execute_creates_event() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "title": "Team standup",
            "start": "2026-02-27T09:00:00",
            "end": "2026-02-27T09:30:00",
        },
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "id": "evt_123",
        "htmlLink": "https://calendar.google.com/event?id=evt_123",
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["created"] is True
    assert result["event_id"] == "evt_123"
    assert result["link"] == "https://calendar.google.com/event?id=evt_123"

    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.call_args[1]
    assert call_kwargs["json"]["summary"] == "Team standup"
    assert call_kwargs["headers"]["Authorization"] == "Bearer fake-token"

    ctx.garden.write_action.assert_awaited_once()


# ── test_execute_missing_required_fields ─────────────────────────────


async def test_execute_missing_required_fields_no_title() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "start": "2026-02-27T09:00:00",
            "end": "2026-02-27T09:30:00",
        },
    )
    result = await execute_fn(ctx)
    assert result["created"] is False
    assert "required" in result["error"]


async def test_execute_missing_required_fields_no_start() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "title": "Event",
            "end": "2026-02-27T09:30:00",
        },
    )
    result = await execute_fn(ctx)
    assert result["created"] is False
    assert "required" in result["error"]


async def test_execute_missing_required_fields_no_end() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "title": "Event",
            "start": "2026-02-27T09:00:00",
        },
    )
    result = await execute_fn(ctx)
    assert result["created"] is False
    assert "required" in result["error"]


async def test_execute_missing_required_fields_empty_input() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(input_data={})
    result = await execute_fn(ctx)
    assert result["created"] is False
    assert "required" in result["error"]


async def test_execute_missing_required_fields_none_input() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(input_data=None)
    result = await execute_fn(ctx)
    assert result["created"] is False
    assert "required" in result["error"]


# ── test_execute_invalid_datetime ────────────────────────────────────


async def test_execute_invalid_datetime_start() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "title": "Event",
            "start": "not-a-date",
            "end": "2026-02-27T09:30:00",
        },
    )
    result = await execute_fn(ctx)
    assert result["created"] is False
    assert "Invalid datetime" in result["error"]
    assert "not-a-date" in result["error"]


async def test_execute_invalid_datetime_end() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "title": "Event",
            "start": "2026-02-27T09:00:00",
            "end": "garbage",
        },
    )
    result = await execute_fn(ctx)
    assert result["created"] is False
    assert "Invalid datetime" in result["error"]
    assert "garbage" in result["error"]


# ── test_execute_api_error ───────────────────────────────────────────


async def test_execute_api_error() -> None:
    import httpx

    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "title": "Event",
            "start": "2026-02-27T09:00:00",
            "end": "2026-02-27T09:30:00",
        },
    )

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
            await execute_fn(ctx)


# ── test optional fields included in request ─────────────────────────


async def test_execute_includes_optional_fields() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "title": "Lunch",
            "start": "2026-02-27T12:00:00",
            "end": "2026-02-27T13:00:00",
            "description": "Team lunch at HQ",
            "location": "Building 5",
        },
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"id": "evt_456", "htmlLink": ""}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["created"] is True
    call_kwargs = mock_client.post.call_args[1]
    assert call_kwargs["json"]["description"] == "Team lunch at HQ"
    assert call_kwargs["json"]["location"] == "Building 5"
