import pytest
from pydantic import ValidationError

from backend.config import Settings


def test_default_configuration_is_development() -> None:
    settings = Settings(_env_file=None)
    assert settings.APP_ENV == "development"
    assert settings.MAX_NODE_TIMEOUT_SECONDS >= settings.DEFAULT_NODE_TIMEOUT_SECONDS


def test_production_requires_runtime_secrets() -> None:
    settings = Settings(APP_ENV="production", _env_file=None)
    with pytest.raises(ValueError, match="CREDENTIALS_ENCRYPTION_KEY"):
        settings.validate_runtime_secrets()


def test_max_timeout_must_cover_default() -> None:
    with pytest.raises(ValidationError):
        Settings(
            DEFAULT_NODE_TIMEOUT_SECONDS=20,
            MAX_NODE_TIMEOUT_SECONDS=10,
            _env_file=None,
        )


def test_enabled_provider_requires_webhook_secret_in_production() -> None:
    settings = Settings(
        APP_ENV="production",
        CREDENTIALS_ENCRYPTION_KEY="configured",
        GITHUB_OAUTH_CLIENT_ID="client",
        _env_file=None,
    )
    with pytest.raises(ValueError, match="GITHUB_WEBHOOK_SECRET"):
        settings.validate_runtime_secrets()
