"""Shared test fixtures and helpers for bsage tests."""

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
