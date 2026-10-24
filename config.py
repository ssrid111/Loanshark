"""Environment-only configuration. Secret values must never enter logs."""

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def validate_database_url(value: SecretStr) -> SecretStr:
    try:
        url = make_url(value.get_secret_value())
        valid = (
            url.drivername == "postgresql+asyncpg"
            and bool(url.host and url.username and url.password and url.database)
            and "REPLACE_" not in value.get_secret_value()
        )
    except Exception:
        raise ValueError("Expected a configured PostgreSQL asyncpg URL") from None
    if not valid:
        raise ValueError("Expected a configured PostgreSQL asyncpg URL without placeholders")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True
    )

    database_url: SecretStr
    default_timezone: str = "America/Phoenix"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    enable_discord: bool = False
    enable_private_api: bool = False
    llm_provider: Literal["none"] = "none"

    _database_url = field_validator("database_url")(validate_database_url)

    @field_validator("enable_discord", "enable_private_api")
    @classmethod
    def integration_not_implemented(cls, value: bool) -> bool:
        if value:
            raise ValueError("This integration is not implemented in the foundation milestone")
        return value

    @field_validator("default_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Expected an IANA time zone") from None
        return value


class MigrationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    migration_database_url: SecretStr
    _database_url = field_validator("migration_database_url")(validate_database_url)
