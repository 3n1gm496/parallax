from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "postgresql://parallax:placeholder@localhost:5432/parallax"
    test_database_url: str = "postgresql://parallax:placeholder@localhost:5433/parallax_test"
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
    # Execution Engine Config
    runtime_dry_run: bool = True
    polymarket_private_key: str = ""
    polymarket_funder: str = ""
    polymarket_chain_id: int = 137
    persist_market_relations_compat: bool = False
    runtime_enable_stream_trigger: bool = False

    # Replay Engine Config
    runtime_recording_mode: bool = False
    runtime_replay_mode: bool = False
    runtime_replay_file: str = ""
    runtime_replay_speed_factor: float = 0.0  # 0.0 = max speed, 1.0 = real-time
    
    # Risk Management / Unwind Engine
    runtime_auto_unwind_enabled: bool = True
    runtime_max_unwind_slippage: float = 0.05  # 5% max slippage on emergency dump
    orderbook_enabled: bool = False
    orderbook_snapshot_ttl_seconds: float = 45.0
    orderbook_fetch_timeout_seconds: float = 5.0
    court_max_quote_staleness_seconds: float = 60.0
    court_min_depth_size: float = 10.0
    court_partial_fill_inversion_threshold: float = 0.4
    kalshi_api_key: str = ""
    kalshi_api_secret: str = ""
    polymarket_clob_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    kalshi_ws_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    ws_reconnect_max_attempts: int = 10
    ws_reconnect_base_delay_seconds: float = 1.0

    # ── Neo4j Knowledge Graph ─────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "placeholder"

    # ── Semantic Agent (NLP) ──────────────────────────────────────────────────
    semantic_agent_model: str = "all-MiniLM-L6-v2"
    semantic_agent_min_similarity: float = 0.88
    semantic_agent_scan_interval_seconds: int = 1800  # Run every 30 minutes

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def prefer_dotenv_for_masked_secrets(self) -> "Settings":
        # Standardize masking for all sensitive keys
        self.anthropic_api_key = _prefer_dotenv_secret(
            current_value=self.anthropic_api_key,
            env_name="ANTHROPIC_API_KEY",
            redacted_prefixes=("sk-ant-",),
        )
        self.polymarket_private_key = _prefer_dotenv_secret(
            current_value=self.polymarket_private_key,
            env_name="POLYMARKET_PRIVATE_KEY",
            redacted_prefixes=("0x",),
        )
        self.kalshi_api_key = _prefer_dotenv_secret(
            current_value=self.kalshi_api_key,
            env_name="KALSHI_API_KEY",
            redacted_prefixes=("",),
        )
        self.kalshi_api_secret = _prefer_dotenv_secret(
            current_value=self.kalshi_api_secret,
            env_name="KALSHI_API_SECRET",
            redacted_prefixes=("",),
        )
        self.neo4j_password = _prefer_dotenv_secret(
            current_value=self.neo4j_password,
            env_name="NEO4J_PASSWORD",
            redacted_prefixes=("",),
        )
        return self

    @property
    def trusted_hosts_list(self) -> list[str]:
        return [item.strip() for item in self.api_trusted_hosts.split(",") if item.strip()]

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [item.strip() for item in self.api_cors_allowed_origins.split(",") if item.strip()]

    def validate_runtime_safety(self) -> None:
        if not self.api_auth_token.strip() or self.api_auth_token == "placeholder":
            if self.app_env.lower() != "dev":
                raise RuntimeError("API_AUTH_TOKEN is required and cannot be 'placeholder' outside dev mode")
        
        if self.app_env.lower() in ("dev", "test"):
            return
        
        # Production-grade safety checks
        if not self.api_require_auth_for_reads:
            raise RuntimeError("API_REQUIRE_AUTH_FOR_READS must be enabled outside dev mode")
        if self.api_docs_enabled:
            raise RuntimeError("API docs must be disabled outside dev mode")
        if not self.trusted_hosts_list:
            raise RuntimeError("API_TRUSTED_HOSTS must be configured outside dev mode")
        if self.neo4j_password == "placeholder" or self.neo4j_password == "parallax":
            raise RuntimeError("NEO4J_PASSWORD must be secure and configured in non-dev mode")
        if "dev_password" in self.database_url or "placeholder" in self.database_url:
             raise RuntimeError("DATABASE_URL must have a secure password in non-dev mode")


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
    try:
        content = env_path.read_text()
        # Better regex-based parser that handles basic quoting
        import re
        pattern = rf"^{env_name}\s*=\s*(.*)$"
        for line in content.splitlines():
            match = re.match(pattern, line)
            if match:
                val = match.group(1).strip()
                # Strip quotes if present
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                return val
    except Exception:
        pass
    return None


settings = Settings()
