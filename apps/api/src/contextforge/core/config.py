"""Runtime configuration, validated once at boot.

Every setting comes from the environment. Security-relevant settings are checked by
``Settings.guard`` so a misconfigured production deployment refuses to start instead of
running with demo secrets.

Redis is optional: leave ``REDIS_URL`` empty and the result cache, rate limits and config
invalidation run in process (correct for one single-process replica, the default; use
Redis for several replicas or WEB_CONCURRENCY above 1).
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_SECRETS = {"", "change-me", "replace-with-output-of-make-env", "dev", "secret"}

# List input prices in USD per 1M tokens, used only to estimate the spend a run avoided.
# Prices change: override with MODEL_PRICES. Unknown models report no estimate.
DEFAULT_PRICES: dict[str, Decimal] = {
    "gpt-4o": Decimal("2.50"),
    "gpt-4o-mini": Decimal("0.15"),
    "gpt-4.1": Decimal("2.00"),
    "gpt-4.1-mini": Decimal("0.40"),
    "gpt-4.1-nano": Decimal("0.10"),
    "o3": Decimal("2.00"),
    "o4-mini": Decimal("1.10"),
    "claude-sonnet-4-5": Decimal("3.00"),
    "claude-haiku-4-5": Decimal("1.00"),
}


def _pairs(value: object) -> object:
    """Parse ``a=b,c=d`` into a dict; pass dicts through."""
    if isinstance(value, str):
        out: dict[str, str] = {}
        for item in value.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                if k.strip():
                    out[k.strip()] = v.strip()
        return out
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "production"] = "development"
    cloud: Literal["local", "floci", "aws"] = Field("local", alias="CONTEXTFORGE_CLOUD")
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://contextforge:contextforge@localhost:4342/contextforge"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Empty: no Redis. Caches, rate limits and config invalidation then run in process.
    redis_url: str = ""

    session_secret: str = "dev-session-secret-not-for-production"  # noqa: S105 dev default, refused in production by guard()
    api_key_pepper: str = "dev-api-key-pepper-not-for-production"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:4310"]
    )

    # Upstream credentials are sealed before they reach the database.
    key_mode: Literal["local", "kms"] = "local"
    local_master_key: str = "dev-local-master-key-not-for-production"
    kms_key_id: str = "alias/contextforge-local"

    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None
    s3_force_path_style: bool = False
    # Job payloads and results, benchmark reports. Rows keep only the object key.
    payloads_bucket: str = "contextforge-local-payloads"
    storage: Literal["local", "s3"] = "local"
    local_storage_dir: str = "./.data/payloads"

    # Service behaviour
    auth_required: bool = Field(
        True, description="Require a cfk_ service key on /v1. Turn off only on a private network"
    )
    default_rpm_limit: int = 600
    result_cache_ttl_s: int = 600
    result_cache_max_bytes: int = 2_000_000
    # Without Redis: the in-process cache's total size (results are evicted oldest first).
    memory_cache_max_bytes: int = Field(64_000_000, ge=1_000_000)
    max_body_bytes: int = 32_000_000
    # Engine runs are CPU bound: cap concurrent runs per process and how long a request
    # waits for a slot before it gets 503 engine_busy (scale with replicas, not threads).
    engine_concurrency: int = Field(4, ge=1, le=64)
    engine_queue_timeout_s: float = Field(10.0, gt=0)
    store_content: bool = False
    tokenizer_aliases: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)
    model_prices: Annotated[dict[str, Decimal], NoDecode] = Field(
        default_factory=lambda: dict(DEFAULT_PRICES)
    )

    # Proxy (/v1/chat/completions)
    upstream_timeout_s: float = 120.0
    default_upstream: str | None = None
    default_proxy_strategy: Literal["conservative", "balanced", "aggressive"] = "balanced"

    # Optional LLM summarizer (any OpenAI-compatible endpoint: TokenShield, SmartRouter, ...)
    llm_summarizer_url: str | None = None
    llm_summarizer_model: str = "gpt-4o-mini"
    llm_summarizer_api_key: str | None = None
    llm_timeout_s: float = 20.0

    # Jobs
    job_poll_interval_s: float = 1.0
    job_lease_s: int = 300
    # The worker serves its own /metrics (job counters, job-side optimize metrics) here;
    # 0 turns it off. The API serves /metrics on its HTTP port.
    worker_metrics_port: int = Field(9464, ge=0, le=65535)

    otel_enabled: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("tokenizer_aliases", mode="before")
    @classmethod
    def _aliases(cls, v: object) -> object:
        return _pairs(v)

    @field_validator("model_prices", mode="before")
    @classmethod
    def _prices(cls, v: object) -> object:
        parsed = _pairs(v)
        if isinstance(parsed, dict) and isinstance(v, str):
            return {**DEFAULT_PRICES, **{k: Decimal(p) for k, p in parsed.items()}}
        return parsed

    @property
    def cache_backend(self) -> Literal["redis", "memory"]:
        return "redis" if self.redis_url else "memory"

    def guard(self) -> None:
        """Refuse to boot in production with demo secrets or unsafe options."""
        if self.environment != "production":
            return
        problems: list[str] = []
        for name in ("session_secret", "api_key_pepper"):
            value = getattr(self, name)
            if value in INSECURE_SECRETS or "not-for-production" in value or len(value) < 32:
                problems.append(f"{name.upper()} must be a random value of at least 32 chars")
        if self.key_mode == "local" and (
            "not-for-production" in self.local_master_key or len(self.local_master_key) < 32
        ):
            problems.append("LOCAL_MASTER_KEY must be set (or use KEY_MODE=kms)")
        if self.session_secret == self.api_key_pepper:
            problems.append("SESSION_SECRET and API_KEY_PEPPER must differ")
        if self.cloud == "aws" and self.aws_endpoint_url:
            problems.append("AWS_ENDPOINT_URL must be unset when CONTEXTFORGE_CLOUD=aws")
        if not self.auth_required:
            problems.append("AUTH_REQUIRED=false is refused in production")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if problems:
            raise RuntimeError("unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.guard()
    return settings
