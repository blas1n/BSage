"""BSage configuration via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Configuration
    llm_model: str = "anthropic/claude-sonnet-4-20250514"
    llm_api_key: str = ""
    llm_api_base: str | None = None

    # Paths
    vault_path: Path = Path("./vault")
    skills_dir: Path = Path("./skills")
    tmp_dir: Path = Path("./tmp")
    credentials_dir: Path = Path("./.credentials")

    # Runtime
    safe_mode: bool = True
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8000
    log_level: str = "info"


def get_settings() -> Settings:
    """Factory function for Settings — allows overriding in tests."""
    return Settings()
