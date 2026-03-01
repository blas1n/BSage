"""Tests for the calendar-input plugin."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {
        "google_api_key": "fake-api-key",
        "calendar_id": "primary",
        "days_ahead": "7",
    }
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "calendar_input", "plugins/calendar-input/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


# ── execute() tests ───────────────────────────────────────────────────


async def test_execute_collects_events() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context()

    mock_response_data = {
        "items": [
            {
                "summary": "Team meeting",
                "start": {"dateTime": "2026-02-27T10:00:00Z"},
                "end": {"dateTime": "2026-02-27T11:00:00Z"},
                "description": "Weekly sync",
                "location": "Room A",
                "attendees": [{"email": "alice@example.com"}, {"email": "bob@example.com"}],
            },
            {
                "summary": "Lunch",
                "start": {"date": "2026-02-28"},
                "end": {"date": "2026-02-28"},
            },
        ]
    }

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=mock_response_data)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result == {"collected": 2}
    ctx.garden.write_seed.assert_awaited_once()
    call_args = ctx.garden.write_seed.call_args
    assert call_args[0][0] == "calendar"
    events = call_args[0][1]["events"]
    assert len(events) == 2
    assert events[0]["title"] == "Team meeting"
    assert events[0]["start"] == "2026-02-27T10:00:00Z"
    assert events[0]["location"] == "Room A"
    assert events[0]["attendees"] == ["alice@example.com", "bob@example.com"]
    assert events[1]["title"] == "Lunch"
    assert events[1]["start"] == "2026-02-28"


async def test_execute_empty_calendar() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context()

    mock_response_data = {"items": []}

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=mock_response_data)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result == {"collected": 0}
    ctx.garden.write_seed.assert_awaited_once()
    events = ctx.garden.write_seed.call_args[0][1]["events"]
    assert events == []


async def test_execute_api_error() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context()

    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )
    )

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(httpx.HTTPStatusError):
            await execute_fn(ctx)
