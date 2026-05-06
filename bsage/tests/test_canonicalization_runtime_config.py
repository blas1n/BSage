"""Tests for runtime-config-driven canonicalization wiring.

Per user requirement: embedding + LLM settings are tenant-configurable
via the existing PATCH /api/config flow (RuntimeConfig). Canon must read
from RuntimeConfig — not env vars / static Settings — so admins can
point at a local Ollama (e.g. http://bsserver:11434) without restart.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from bsage.core.config import Settings
from bsage.core.runtime_config import RuntimeConfig
from bsage.gateway.canonicalization_routes import (
    _embedder_callable,
    _verifier_callable,
)


def _make_runtime_config(**overrides) -> RuntimeConfig:
    base: dict = {
        "llm_model": "",
        "llm_api_key": "",
        "llm_api_base": None,
        "safe_mode": False,
        "bsgateway_url": "",
        "disabled_entries": [],
        "embedding_model": "",
        "embedding_api_key": "",
        "embedding_api_base": None,
    }
    base.update(overrides)
    return RuntimeConfig(persist_path=None, **base)


class TestRuntimeConfigShape:
    def test_embedding_fields_present(self) -> None:
        cfg = _make_runtime_config()
        assert hasattr(cfg, "embedding_model")
        assert hasattr(cfg, "embedding_api_key")
        assert hasattr(cfg, "embedding_api_base")

    def test_embedding_api_key_is_secret(self) -> None:
        cfg = _make_runtime_config(embedding_api_key="sk-secret")
        snap = cfg.snapshot()
        # Secret fields are excluded from snapshot per existing convention
        assert "embedding_api_key" not in snap
        # Public fields are included
        assert "embedding_model" in snap
        assert "embedding_api_base" in snap

    def test_update_persists(self, tmp_path: Path) -> None:
        cfg = _make_runtime_config()
        cfg.update(
            embedding_model="ollama/nomic-embed-text",
            embedding_api_base="http://bsserver:11434",
        )
        assert cfg.embedding_model == "ollama/nomic-embed-text"
        assert cfg.embedding_api_base == "http://bsserver:11434"

    def test_settings_round_trip(self, tmp_path: Path) -> None:
        # Settings env values become RuntimeConfig defaults; persisted
        # JSON file overrides them. Embedding follows the same pattern as LLM.
        s = Settings(
            llm_model="anthropic/claude-3",
            llm_api_key="lk-key",
            embedding_model="ollama/nomic",
            embedding_api_key="ek-key",
            embedding_api_base="http://bsserver:11434",
        )
        cfg = RuntimeConfig.from_settings(s, persist_path=tmp_path / "rc.json")
        assert cfg.embedding_model == "ollama/nomic"
        assert cfg.embedding_api_key == "ek-key"
        assert cfg.embedding_api_base == "http://bsserver:11434"


class TestEmbedderCallable:
    def test_returns_none_when_model_empty(self) -> None:
        state = MagicMock()
        state.runtime_config = _make_runtime_config()
        assert _embedder_callable(state) is None

    def test_returns_callable_when_model_set(self) -> None:
        state = MagicMock()
        state.runtime_config = _make_runtime_config(
            embedding_model="ollama/nomic-embed-text",
            embedding_api_base="http://bsserver:11434",
        )
        fn = _embedder_callable(state)
        assert fn is not None

    def test_picks_up_runtime_changes(self) -> None:
        # Same state, mutate runtime_config — embedder callable should see
        # the new config without rebuilding the AppState.
        state = MagicMock()
        state.runtime_config = _make_runtime_config()
        assert _embedder_callable(state) is None

        state.runtime_config.update(embedding_model="ollama/test")
        fn_after = _embedder_callable(state)
        assert fn_after is not None


class TestVerifierCallable:
    def test_returns_none_when_llm_model_empty(self) -> None:
        state = MagicMock()
        state.runtime_config = _make_runtime_config()
        assert _verifier_callable(state) is None

    def test_returns_callable_when_llm_model_set(self) -> None:
        state = MagicMock()
        state.runtime_config = _make_runtime_config(
            llm_model="ollama/qwen2.5", llm_api_base="http://bsserver:11434"
        )
        fn = _verifier_callable(state)
        assert fn is not None

    def test_does_not_read_static_settings(self) -> None:
        # Verifier MUST NOT use state.settings.llm_model — runtime_config wins.
        state = MagicMock()
        state.runtime_config = _make_runtime_config()  # llm_model=""
        # Settings has llm_model set, but runtime_config doesn't — must skip
        state.settings = MagicMock(llm_model="anthropic/claude-3")
        assert _verifier_callable(state) is None


class TestConfigUpdateAcceptsEmbedding:
    """ConfigUpdate Pydantic model accepts new embedding_* fields."""

    def test_pydantic_validates_embedding_fields(self) -> None:
        from bsage.gateway.routes import ConfigUpdate

        u = ConfigUpdate(
            embedding_model="ollama/nomic",
            embedding_api_base="http://bsserver:11434",
            embedding_api_key="ek-key",
        )
        assert u.embedding_model == "ollama/nomic"
        assert u.embedding_api_base == "http://bsserver:11434"
        assert u.embedding_api_key == "ek-key"
        # All three opt-in fields appear in model_fields_set when supplied
        assert {"embedding_model", "embedding_api_base", "embedding_api_key"} <= u.model_fields_set
