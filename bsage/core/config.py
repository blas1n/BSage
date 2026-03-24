"""BSage configuration via pydantic-settings."""

from pathlib import Path

from pydantic import Field
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
    plugins_dir: Path = Path("./plugins")
    tmp_dir: Path = Path("./tmp")
    credentials_dir: Path = Path("./.credentials")
    prompts_dir: Path = Path("./prompts")

    # Embedding / Vector search (empty model = disabled)
    embedding_model: str = ""
    embedding_api_key: str = ""
    embedding_api_base: str | None = None

    # Maturity lifecycle thresholds
    maturity_seedling_min_relationships: int = Field(default=2, gt=0)
    maturity_budding_min_sources: int = Field(default=3, gt=0)
    maturity_evergreen_min_days_stable: int = Field(default=14, gt=0)
    maturity_evergreen_min_relationships: int = Field(default=5, gt=0)

    # Confidence decay — halflife in days per knowledge layer
    decay_halflife_semantic: int = Field(default=365, gt=0)
    decay_halflife_episodic: int = Field(default=30, gt=0)
    decay_halflife_procedural: int = Field(default=90, gt=0)
    decay_halflife_affective: int = Field(default=60, gt=0)

    # Edge lifecycle
    edge_promotion_min_mentions: int = Field(default=3, gt=0)
    edge_decay_days: int = Field(default=90, gt=0)

    # Embedding text limit
    max_embed_chars: int = Field(default=8000, gt=0)

    # Authentication (Supabase)
    supabase_jwt_secret: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # Runtime
    safe_mode: bool = True
    disabled_entries: list[str] = []
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000
    log_level: str = "info"


def get_settings() -> Settings:
    """Factory function for Settings — allows overriding in tests."""
    return Settings()
