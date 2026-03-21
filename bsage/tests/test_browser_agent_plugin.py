"""Tests for the browser-agent plugin."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bsage.tests.conftest import make_plugin_context

_DEFAULT_INPUT = {"url": "https://example.com", "task": "extract page title"}


def _make_context() -> MagicMock:
    return make_plugin_context(
        input_data=_DEFAULT_INPUT,
        include_write_action=True,
        include_notify=True,
    )


def _load_plugin():
    """Import the plugin module and return (execute, module)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "browser_agent", "plugins/browser-agent/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute, mod


@pytest.mark.asyncio
async def test_execute_missing_url() -> None:
    """Test that execute returns error when url is missing."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"task": "extract"}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "url" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_execute_missing_task() -> None:
    """Test that execute returns error when task is missing."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"url": "https://example.com"}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "task" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_execute_empty_input() -> None:
    """Test that execute returns error when input is empty."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {}

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_execute_invalid_selector() -> None:
    """Test that execute rejects selectors with disallowed characters."""
    execute_fn, _ = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {
        "url": "https://example.com",
        "task": "extract",
        "extract_selector": "<script>alert(1)</script>",
    }

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "invalid" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_execute_valid_selector_accepted() -> None:
    """Test that valid CSS selectors pass validation."""
    execute_fn, mod = _load_plugin()
    # Patch _browser_task to avoid needing real playwright
    mock_result = {
        "success": True,
        "url": "https://example.com",
        "page_title": "Example",
        "content": "Hello World",
    }
    with patch.object(mod, "_browser_task", new_callable=AsyncMock, return_value=mock_result):
        ctx = _make_context()
        ctx.input_data = {
            "url": "https://example.com",
            "task": "extract",
            "extract_selector": ".article-title h2",
        }

        result = await execute_fn(ctx)

    assert result["success"] is True


@pytest.mark.asyncio
async def test_execute_success_with_mocked_browser() -> None:
    """Test successful execution with mocked browser task."""
    execute_fn, mod = _load_plugin()
    mock_result = {
        "success": True,
        "url": "https://example.com",
        "page_title": "Example Domain",
        "content": "This domain is for use in illustrative examples.",
    }
    with patch.object(mod, "_browser_task", new_callable=AsyncMock, return_value=mock_result):
        ctx = _make_context()
        result = await execute_fn(ctx)

    assert result["success"] is True
    assert result["page_title"] == "Example Domain"
    assert "illustrative" in result["content"]
    ctx.garden.write_action.assert_awaited_once()
    ctx.garden.write_seed.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_browser_task_exception() -> None:
    """Test that exceptions in browser task are handled gracefully."""
    execute_fn, mod = _load_plugin()
    side_effect = RuntimeError("boom")
    with patch.object(mod, "_browser_task", new_callable=AsyncMock, side_effect=side_effect):
        ctx = _make_context()
        result = await execute_fn(ctx)

    assert result["success"] is False
    assert "boom" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_url_auto_prefix() -> None:
    """Test that URLs without scheme get https:// prepended."""
    execute_fn, mod = _load_plugin()
    mock_result = {
        "success": True,
        "url": "https://example.com",
        "page_title": "Example",
        "content": "ok",
    }
    with patch.object(
        mod, "_browser_task", new_callable=AsyncMock, return_value=mock_result
    ) as mock_bt:
        ctx = _make_context()
        ctx.input_data = {"url": "example.com", "task": "test"}
        await execute_fn(ctx)

    # First positional arg to _browser_task should be the prefixed URL
    call_args = mock_bt.call_args
    assert call_args[0][0] == "https://example.com"


@pytest.mark.asyncio
async def test_browser_task_playwright_not_installed() -> None:
    """Test graceful error when playwright is not installed."""
    _, mod = _load_plugin()
    logger = MagicMock()

    import builtins

    original_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if "playwright" in name:
            raise ImportError("no playwright")
        return original_import(name, *a, **kw)

    with patch("builtins.__import__", side_effect=fake_import):
        result = await mod._browser_task("https://example.com", "test", "", "", True, logger)

    assert result["success"] is False
    assert "playwright" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_notify_sends_content() -> None:
    """Test notify handler sends content via context.notify."""
    _, mod = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {
        "content": "Extracted text from page",
        "page_title": "Test Page",
        "url": "https://example.com",
    }

    result = await mod.notify(ctx)

    assert result["sent"] is True
    ctx.notify.send.assert_awaited_once()
    sent_msg = ctx.notify.send.call_args[0][0]
    assert "Extracted text" in sent_msg


@pytest.mark.asyncio
async def test_notify_no_content() -> None:
    """Test notify returns not sent when content is empty."""
    _, mod = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {"content": "", "page_title": "", "url": ""}

    result = await mod.notify(ctx)

    assert result["sent"] is False


@pytest.mark.asyncio
async def test_notify_no_channel() -> None:
    """Test notify returns not sent when no channel available."""
    _, mod = _load_plugin()
    ctx = _make_context()
    ctx.notify = None
    ctx.input_data = {
        "content": "Some content",
        "page_title": "Page",
        "url": "https://example.com",
    }

    result = await mod.notify(ctx)

    assert result["sent"] is False
    assert "no notification channel" in result.get("reason", "")


@pytest.mark.asyncio
async def test_notify_truncates_long_content() -> None:
    """Test notify truncates content longer than 2000 chars."""
    _, mod = _load_plugin()
    ctx = _make_context()
    ctx.input_data = {
        "content": "x" * 5000,
        "page_title": "Page",
        "url": "https://example.com",
    }

    result = await mod.notify(ctx)

    assert result["sent"] is True
    sent_msg = ctx.notify.send.call_args[0][0]
    assert "truncated" in sent_msg
