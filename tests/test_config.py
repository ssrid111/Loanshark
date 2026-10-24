import pytest
from pydantic import SecretStr, ValidationError

from config import MigrationSettings, Settings


@pytest.mark.parametrize(
    "value",
    [
        "sqlite:///local.db",
        "postgresql://u:p@localhost/db",
        "not-a-url",
        "postgresql+asyncpg://u:REPLACE_PASSWORD@localhost/db",
    ],
)
def test_invalid_database_configuration(value: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=SecretStr(value))
    assert value not in str(error.value)


def test_settings_hide_credentials(settings: Settings) -> None:
    assert "test:test" not in repr(settings)
    assert settings.enable_discord is False
    assert settings.enable_private_api is False


def test_unimplemented_integration_cannot_be_enabled(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, enable_discord=True)


def test_invalid_timezone(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=settings.database_url, default_timezone="not/a-zone")


def test_runtime_settings_do_not_load_migration_secret(settings: Settings) -> None:
    assert "migration_database_url" not in type(settings).model_fields
    with pytest.raises(ValidationError):
        MigrationSettings(_env_file=None, migration_database_url=SecretStr("invalid"))
