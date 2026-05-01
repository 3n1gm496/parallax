from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://parallax:dev_password@localhost:5432/parallax"
    test_database_url: str = "postgresql://parallax:dev_password@localhost:5433/parallax_test"
    anthropic_api_key: str = "placeholder"
    polymarket_polling_interval_seconds: int = 300
    polymarket_max_events_per_poll: int = 50
    friction_bps: int = 50

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
