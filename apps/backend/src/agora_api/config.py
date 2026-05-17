"""Application settings, loaded from environment via Pydantic."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings sourced from .env / environment."""

    # App
    app_env: Literal["local", "dev", "staging", "production"] = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Database
    database_url: str = "postgresql+asyncpg://agora:agora_dev_change_me@localhost:5432/agora"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Search / Vector (optional in bootstrap phase per ADR 003)
    use_typesense: bool = False
    use_qdrant: bool = False
    typesense_host: str = "localhost"
    typesense_port: int = 8108
    typesense_api_key: str = "agora_dev_typesense_key"
    qdrant_url: str = "http://localhost:6333"

    # Blockchain (off-chain ledger in bootstrap phase)
    enable_onchain_payments: bool = False
    chain_id: int = 84532  # Base Sepolia
    rpc_url: str = "https://sepolia.base.org"
    escrow_contract_address: str = ""
    usdc_contract_address: str = ""

    # Auth / Custody (Privy - ADR 005)
    privy_app_id: str = ""
    privy_app_secret: str = ""

    # Webhook signing (ADR 008): Ed25519 keypair for outbound webhooks.
    agora_signing_private_key_b64: str = ""
    agora_signing_key_id: str = "agora-local-dev"
    webhook_max_attempts: int = 6
    webhook_request_timeout_seconds: float = 10.0
    webhook_worker_poll_interval_seconds: float = 5.0
    webhook_worker_enabled: bool = True

    # Fee model (ADR 004): 1.0% with min 0.50 EUR and max 25 EUR
    fee_bps: int = 100
    fee_min_eur: Decimal = Decimal("0.50")
    fee_max_eur: Decimal = Decimal("25.00")
    insurance_share_bps: int = 1000

    # LLM Providers
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "./var/storage"

    # Feature Flags
    enable_dispute: bool = False
    enable_reputation: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
