"""BSage configuration via pydantic-settings.

Phase A migration (2026-04-26): :class:`Settings` now extends
:class:`bsvibe_core.BsvibeSettings` so the four-product
``Annotated[list[str], NoDecode]`` CSV-env contract (BSupervisor §M18)
is shared rather than re-derived. ``cors_origins`` adopts
:func:`bsvibe_core.csv_list_field` so deployers can use either the
legacy JSON form (``["http://a"]``) or the simpler CSV form
(``http://a,http://b``) without crashes.
"""

import json
from pathlib import Path
from typing import Annotated

from bsvibe_core import BsvibeSettings, parse_csv_list
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import NoDecode, SettingsConfigDict

_DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


class Settings(BsvibeSettings):
    """Application settings loaded from environment variables and .env file.

    Inherits the BSVibe baseline (case-insensitive env, ``extra="ignore"``)
    from :class:`BsvibeSettings` and re-pins ``env_file=".env"`` so BSage
    keeps loading its existing dotfiles.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM Configuration
    llm_model: str = "anthropic/claude-sonnet-4-20250514"
    llm_api_key: str = ""
    llm_api_base: str | None = None
    # When set, BSage routes LLM calls through BSGateway via bsvibe-llm
    # for shared run-audit metadata + cost tracking. Empty = direct vendor.
    bsgateway_url: str = ""

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

    # Credential encryption (Fernet symmetric encryption)
    # Primary key — used for encrypting new writes. If empty, encryption is
    # disabled and credentials remain plaintext (legacy mode for local-only
    # development). Production deployments MUST set this.
    credential_encryption_key: str = ""
    # Retired keys (comma-separated, oldest first) — accepted for decryption
    # of older ciphertexts during key rotation. After rotation completes,
    # remove old keys here once all stored credentials are re-encrypted.
    credential_encryption_retired_keys: list[str] = []

    # Authentication (BSVibe)
    bsvibe_auth_url: str = "https://auth.bsvibe.dev"

    # OAuth2 client_credentials grant — see BSVibe-Auth `/api/oauth/token`.
    # Optional; needed only when BSage initiates service-to-service calls.
    # Each backend has a dedicated row in `oauth_clients`; the secret is
    # provisioned once and stored in Vaultwarden.
    bsvibe_client_id: str = ""
    bsvibe_client_secret: str = ""

    # Service-to-service API keys (JSON: {"service-name": "key"})
    # DEPRECATED Phase 0 P0.5+: use service JWTs (audience=bsage) instead.
    # Kept so existing deployments don't 401 mid-rollout.
    service_api_keys: dict[str, str] = {}

    # bsvibe-authz / OpenFGA (Phase 0 P0.5)
    # Empty openfga_api_url disables OpenFGA enforcement (local dev mode).
    openfga_api_url: str = ""
    openfga_store_id: str = ""
    openfga_auth_model_id: str = ""
    openfga_auth_token: str = ""
    service_token_signing_secret: str = ""

    # Default tenant id used when a write happens without an authenticated
    # principal (cron, local dev, or migration). Personal-tenant only.
    default_tenant_id: str = "tenant-default"

    # CORS — Annotated[list[str], NoDecode] + parse_csv_list per the
    # BSVibe four-product contract (bsvibe_core.csv_list_field). Accepts
    # either the legacy JSON shape (``["http://a"]``) or the operator-
    # friendly CSV shape (``http://a,http://b``).
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_CORS_ORIGINS),
        validation_alias=AliasChoices("cors_origins", "cors_allowed_origins"),
        description="Allowed CORS origins for the BSage gateway",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                try:
                    decoded = json.loads(stripped)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, list):
                    return parse_csv_list(decoded) or list(_DEFAULT_CORS_ORIGINS)
            return parse_csv_list(stripped) or list(_DEFAULT_CORS_ORIGINS)
        if isinstance(v, list):
            return [str(x) for x in v]
        return list(_DEFAULT_CORS_ORIGINS)

    # Rate limiting
    rate_limit_per_minute: int = Field(default=60, gt=0)

    # Ingest compiler
    ingest_compile_enabled: bool = True
    ingest_compile_max_updates: int = 10

    # Runtime
    safe_mode: bool = True
    disabled_entries: list[str] = []
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000
    log_level: str = "info"


def get_settings() -> Settings:
    """Factory function for Settings — allows overriding in tests."""
    return Settings()
