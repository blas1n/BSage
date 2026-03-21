"""Shared test fixtures and helpers for bsage tests."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
) -> MagicMock:
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
        root = vault_root or Path("/tmp")
        ctx.garden.resolve_plugin_state_path = MagicMock(
            side_effect=lambda plugin_name, subpath="_state.json": (
                root / "seeds" / plugin_name / subpath
            ),
        )

    # Chat
    ctx.chat = AsyncMock() if include_chat else None

    # Notify
    ctx.notify = AsyncMock() if include_notify else None

    # Config
    if config_overrides:
        config = MagicMock()
        for k, v in config_overrides.items():
            setattr(config, k, v)
        ctx.config = config

    return ctx


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
