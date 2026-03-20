import logging
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Climate Alerts API"
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/climate_alerts"
    mock_whatsapp_url: str | None = None
    mock_whatsapp_hostport: str | None = None
    log_level: str = "INFO"
    max_lookahead_days: int = 30
    worker_interval_minutes: int = 1
    worker_failure_backoff_seconds: int = 10
    worker_delivery_batch_size: int = 200
    delivery_max_retries: int = 3
    delivery_backoff_minutes: str = "1,5,15"
    request_timeout_seconds: int = 10
    mock_whatsapp_fail_first_delivery: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError(f"Unsupported log level: {value}")
        return normalized

    @field_validator(
        "max_lookahead_days",
        "worker_interval_minutes",
        "worker_failure_backoff_seconds",
        "worker_delivery_batch_size",
        "delivery_max_retries",
        "request_timeout_seconds",
    )
    @classmethod
    def validate_positive_integer(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        return value

    @field_validator("delivery_backoff_minutes")
    @classmethod
    def validate_delivery_backoff_minutes(cls, value: str) -> str:
        raw_values = [part.strip() for part in value.split(",") if part.strip()]
        if not raw_values:
            raise ValueError("delivery_backoff_minutes must include at least one positive integer")

        try:
            parsed_values = [int(part) for part in raw_values]
        except ValueError as exc:
            raise ValueError("delivery_backoff_minutes must contain only integers") from exc

        if any(parsed_value < 1 for parsed_value in parsed_values):
            raise ValueError("delivery_backoff_minutes values must be >= 1")

        return ",".join(str(parsed_value) for parsed_value in parsed_values)

    @model_validator(mode="after")
    def normalize_runtime_urls(self) -> "Settings":
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace("postgres://", "postgresql://", 1)
        if self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        if not self.mock_whatsapp_url:
            if self.mock_whatsapp_hostport:
                self.mock_whatsapp_url = f"http://{self.mock_whatsapp_hostport}/webhook/whatsapp"
            else:
                self.mock_whatsapp_url = "http://mock-whatsapp:8010/webhook/whatsapp"

        return self

    @property
    def parsed_backoff_minutes(self) -> list[int]:
        return [int(value.strip()) for value in self.delivery_backoff_minutes.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
