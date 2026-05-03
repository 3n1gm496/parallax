from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "postgresql://parallax:dev_password@localhost:5432/parallax"
    test_database_url: str = "postgresql://parallax:dev_password@localhost:5433/parallax_test"
    anthropic_api_key: str = "placeholder"
    polymarket_polling_interval_seconds: int = 300
    polymarket_max_events_per_poll: int = 50
    kalshi_max_events_per_poll: int = 50
    ingestion_adapter_timeout_seconds: int = 45
    pipeline_max_open_markets: int = 0
    friction_bps: int = 50
    compiler_min_confidence: float = 0.5
    semantic_min_relation_confidence: float = 0.7
    court_max_composite_risk: float = 0.4
    court_min_simulated_pnl: float = 0.01
    court_min_fill_probability: float = 0.55
    api_docs_enabled: bool = False
    api_auth_token: str = ""
    api_require_auth_for_reads: bool = False
    api_trusted_hosts: str = "localhost,127.0.0.1,testserver"
    api_cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    provider_freshness_threshold_minutes: int = 180
    runtime_global_pause: bool = False
    runtime_pause_polymarket: bool = False
    runtime_pause_kalshi: bool = False
    runtime_semantic_analysis_disabled: bool = False
    runtime_live_execution_enabled: bool = False
    runtime_degraded_read_only: bool = False
    runtime_max_exposure: float = 1000.0
    runtime_max_daily_loss: float = 250.0
    runtime_max_candidate_concurrency: int = 10
    persist_market_relations_compat: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def prefer_dotenv_for_masked_secrets(self) -> "Settings":
        self.anthropic_api_key = _prefer_dotenv_secret(
            current_value=self.anthropic_api_key,
            env_name="ANTHROPIC_API_KEY",
            redacted_prefixes=("sk-ant-",),
        )
        return self

    @property
    def trusted_hosts_list(self) -> list[str]:
        return [item.strip() for item in self.api_trusted_hosts.split(",") if item.strip()]

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [item.strip() for item in self.api_cors_allowed_origins.split(",") if item.strip()]

    def validate_runtime_safety(self) -> None:
        if self.app_env.lower() == "dev":
            return
        if not self.api_auth_token.strip():
            raise RuntimeError("API_AUTH_TOKEN is required outside dev mode")
        if not self.api_require_auth_for_reads:
            raise RuntimeError("API_REQUIRE_AUTH_FOR_READS must be enabled outside dev mode")
        if self.api_docs_enabled:
            raise RuntimeError("API docs must be disabled outside dev mode")
        if not self.trusted_hosts_list:
            raise RuntimeError("API_TRUSTED_HOSTS must be configured outside dev mode")


def _prefer_dotenv_secret(
    *,
    current_value: str,
    env_name: str,
    redacted_prefixes: tuple[str, ...],
) -> str:
    current = (current_value or "").strip()
    if not _looks_redacted(current, redacted_prefixes):
        return current

    dotenv_value = _read_dotenv_value(env_name)
    if dotenv_value and not _looks_redacted(dotenv_value, redacted_prefixes):
        return dotenv_value
    return current


def _looks_redacted(value: str, prefixes: tuple[str, ...]) -> bool:
    if not value:
        return False
    if value == "placeholder":
        return True
    return value.endswith("...") and value.startswith(prefixes)


def _read_dotenv_value(env_name: str) -> str | None:
    env_path = Path(".env")
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{env_name}="):
            return line.split("=", 1)[1].strip()
    return None


settings = Settings()
