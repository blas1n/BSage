"""Tests for bsage.core.config — pydantic-settings configuration."""

from pathlib import Path

import pytest

from bsage.core.config import Settings, get_settings


class TestSettings:
    """Test Settings loads from env vars and provides defaults."""

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings should have sensible defaults."""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        monkeypatch.delenv("VAULT_PATH", raising=False)
        monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-20250514")

        settings = Settings(_env_file=None)

        assert settings.llm_model == "anthropic/claude-sonnet-4-20250514"
        assert settings.llm_api_key == ""
        assert settings.llm_api_base is None
        assert settings.vault_path == Path("./vault")
        assert settings.skills_dir == Path("./skills")
        assert settings.tmp_dir == Path("./tmp")
        assert settings.credentials_dir == Path("./.credentials")
        assert settings.safe_mode is True
        assert settings.gateway_host == "0.0.0.0"
        assert settings.gateway_port == 8000
        assert settings.log_level == "info"

    def test_loads_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings should load values from environment variables."""
        monkeypatch.setenv("LLM_MODEL", "ollama/llama3")
        monkeypatch.setenv("LLM_API_KEY", "test-key-123")
        monkeypatch.setenv("LLM_API_BASE", "http://localhost:11434")
        monkeypatch.setenv("VAULT_PATH", "/tmp/test-vault")
        monkeypatch.setenv("SAFE_MODE", "false")
        monkeypatch.setenv("GATEWAY_PORT", "9000")
        monkeypatch.setenv("LOG_LEVEL", "debug")

        settings = Settings(_env_file=None)

        assert settings.llm_model == "ollama/llama3"
        assert settings.llm_api_key == "test-key-123"
        assert settings.llm_api_base == "http://localhost:11434"
        assert settings.vault_path == Path("/tmp/test-vault")
        assert settings.safe_mode is False
        assert settings.gateway_port == 9000
        assert settings.log_level == "debug"

    def test_llm_api_key_is_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """API key should be optional (empty string default) for Ollama usage."""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        settings = Settings(_env_file=None)
        assert settings.llm_api_key == ""

    def test_llm_api_base_is_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """API base should be None by default."""
        monkeypatch.delenv("LLM_API_BASE", raising=False)
        settings = Settings(_env_file=None)
        assert settings.llm_api_base is None

    def test_maturity_threshold_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Maturity lifecycle thresholds should have sensible defaults."""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        settings = Settings(_env_file=None)
        assert settings.maturity_seedling_min_relationships == 2
        assert settings.maturity_budding_min_sources == 3
        assert settings.maturity_evergreen_min_days_stable == 14
        assert settings.maturity_evergreen_min_relationships == 5

    def test_embedding_config_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Embedding config should be disabled by default."""
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        settings = Settings(_env_file=None)
        assert settings.embedding_model == ""
        assert settings.embedding_api_key == ""
        assert settings.embedding_api_base is None

    def test_embedding_config_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Embedding config should be loadable from env vars."""
        monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
        monkeypatch.setenv("EMBEDDING_API_KEY", "sk-embed-key")
        monkeypatch.setenv("EMBEDDING_API_BASE", "http://localhost:11434")
        settings = Settings(_env_file=None)
        assert settings.embedding_model == "text-embedding-3-small"
        assert settings.embedding_api_key == "sk-embed-key"
        assert settings.embedding_api_base == "http://localhost:11434"

    def test_maturity_thresholds_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Maturity thresholds should be configurable via env vars."""
        monkeypatch.setenv("MATURITY_SEEDLING_MIN_RELATIONSHIPS", "5")
        monkeypatch.setenv("MATURITY_BUDDING_MIN_SOURCES", "4")
        settings = Settings(_env_file=None)
        assert settings.maturity_seedling_min_relationships == 5
        assert settings.maturity_budding_min_sources == 4


    def test_rejects_zero_maturity_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Maturity thresholds must be positive."""
        monkeypatch.setenv("MATURITY_SEEDLING_MIN_RELATIONSHIPS", "0")
        with pytest.raises(ValueError):
            Settings(_env_file=None)

    def test_rejects_negative_decay_halflife(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decay halflife must be positive."""
        monkeypatch.setenv("DECAY_HALFLIFE_SEMANTIC", "-1")
        with pytest.raises(ValueError):
            Settings(_env_file=None)

    def test_rejects_zero_edge_decay_days(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Edge decay days must be positive."""
        monkeypatch.setenv("EDGE_DECAY_DAYS", "0")
        with pytest.raises(ValueError):
            Settings(_env_file=None)


class TestGetSettings:
    """Test the get_settings() factory function."""

    def test_returns_settings_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        settings = get_settings()
        assert isinstance(settings, Settings)
