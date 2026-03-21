"""Shared test fixtures and helpers for bsage tests."""

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from bsage.core.plugin_loader import PluginMeta
from bsage.core.skill_loader import SkillMeta


def make_skill_meta(**overrides: Any) -> SkillMeta:
    defaults: dict[str, Any] = {
        "name": "test-skill",
        "version": "1.0.0",
        "category": "process",
        "description": "Test skill",
    }
    defaults.update(overrides)
    return SkillMeta(**defaults)


def make_plugin_meta(**overrides: Any) -> PluginMeta:
    defaults: dict[str, Any] = {
        "name": "test-plugin",
        "version": "1.0.0",
        "category": "process",
        "description": "Test plugin",
    }
    defaults.update(overrides)
    return PluginMeta(**defaults)


def make_plugin_context(
    *,
    input_data: dict | None = None,
    credentials: dict | None = None,
    vault_root: Path | None = None,
    include_chat: bool = False,
    include_notify: bool = False,
    include_write_action: bool = False,
    include_state_path: bool = False,
    config_overrides: dict[str, Any] | None = None,
) -> "MagicMock":
    """Create a mock plugin context with configurable attributes.

    Args:
        input_data: Plugin input payload.
        credentials: Plugin credentials dict.
        vault_root: Base path for vault/state resolution.
        include_chat: Attach a mock ChatBridge (default: None).
        include_notify: Attach a mock notify interface.
        include_write_action: Attach garden.write_action mock.
        include_state_path: Attach garden.resolve_plugin_state_path mock.
        config_overrides: Dict of config attribute overrides
            (e.g. vault_path, tmp_dir, safe_mode).
    """
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {}
    ctx.logger = MagicMock()

    # Garden
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    if include_write_action:
        ctx.garden.write_action = AsyncMock()
    if include_state_path:
        root = vault_root or Path("/nonexistent")
        ctx.garden.resolve_plugin_state_path = MagicMock(
            side_effect=lambda plugin_name, subpath="_state.json": (
                root / "seeds" / plugin_name / subpath
            ),
        )

    # Chat
    ctx.chat = AsyncMock() if include_chat else None

    # Notify
    if include_notify:
        ctx.notify = AsyncMock()
        ctx.notify.send = AsyncMock()
    else:
        ctx.notify = None

    # Config — always provide defaults so tests don't need to pass them manually
    config = MagicMock()
    config.vault_path = vault_root or Path(tempfile.gettempdir()) / "bsage-test-vault"
    config.tmp_dir = Path(tempfile.gettempdir()) / "bsage-test-tmp"
    config.safe_mode = True
    if config_overrides:
        for k, v in config_overrides.items():
            setattr(config, k, v)
    ctx.config = config

    return ctx


def make_httpx_response(
    *,
    status_code: int = 200,
    json_data: Any = None,
    text: str = "",
    raise_for_status_error: bool = False,
) -> MagicMock:
    """Create a mock that matches httpx.Response interface."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or (json.dumps(json_data) if json_data is not None else "")
    resp.content = resp.text.encode()
    resp.json = MagicMock(return_value=json_data if json_data is not None else {})
    if raise_for_status_error or status_code >= 400:
        exc = httpx.HTTPStatusError(f"HTTP {status_code}", request=MagicMock(), response=resp)
        resp.raise_for_status = MagicMock(side_effect=exc)
    else:
        resp.raise_for_status = MagicMock()
    return resp


def make_httpx_mock(*, get_response=None, post_response=None):
    """Create a mock httpx.AsyncClient context manager.

    Returns (patch_context, mock_client) where patch_context is used as a
    ``with`` statement and mock_client can be inspected after the call.

    Usage::

        with make_httpx_mock(get_response=mock_resp) as mock_client:
            result = await execute_fn(ctx)
        mock_client.get.assert_awaited_once()
    """
    from contextlib import contextmanager
    from unittest.mock import patch

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    if get_response is not None:
        mock_client.get = AsyncMock(return_value=get_response)
    if post_response is not None:
        mock_client.post = AsyncMock(return_value=post_response)

    @contextmanager
    def _ctx():
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            yield mock_client

    return _ctx()


@pytest.fixture()
def mock_context():
    ctx = MagicMock()
    ctx.logger = MagicMock()
    ctx.credentials = {}
    ctx.garden = AsyncMock()
    ctx.llm = AsyncMock()
    ctx.llm.chat = AsyncMock(return_value="LLM response text")
    ctx.config = {}
    ctx.input_data = None
    return ctx
