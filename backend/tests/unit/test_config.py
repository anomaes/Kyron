from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.config import Settings


def test_default_configuration_is_development() -> None:
    settings = Settings(_env_file=None)
    assert settings.APP_ENV == "development"
    assert settings.MAX_NODE_TIMEOUT_SECONDS >= settings.DEFAULT_NODE_TIMEOUT_SECONDS
    assert settings.TERMINAL_WORKTREE_RETENTION_DAYS == 1
    assert settings.ORPHAN_WORKTREE_GRACE_HOURS == 24
    assert settings.LONG_OPEN_CHANGE_REQUEST_WARNING_DAYS == 14


def test_log_level_is_normalized_and_validated() -> None:
    assert Settings(LOG_LEVEL="debug", _env_file=None).LOG_LEVEL == "DEBUG"
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        Settings(LOG_LEVEL="verbose", _env_file=None)


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


def test_pi_models_config_path_is_optional_and_must_be_absolute() -> None:
    assert Settings(_env_file=None).PI_MODELS_CONFIG_PATH is None
    assert Settings(PI_MODELS_CONFIG_PATH="", _env_file=None).PI_MODELS_CONFIG_PATH is None
    configured = Settings(
        PI_MODELS_CONFIG_PATH="/var/workflowengine/pi/models.json", _env_file=None
    )
    assert configured.PI_MODELS_CONFIG_PATH == Path("/var/workflowengine/pi/models.json")
    with pytest.raises(ValidationError, match="absolute path"):
        Settings(PI_MODELS_CONFIG_PATH="pi/models.json", _env_file=None)


def test_enabled_provider_requires_webhook_secret_in_production() -> None:
    settings = Settings(
        APP_ENV="production",
        CREDENTIALS_ENCRYPTION_KEY="configured",
        GITHUB_OAUTH_CLIENT_ID="client",
        _env_file=None,
    )
    with pytest.raises(ValueError, match="GITHUB_WEBHOOK_SECRET"):
        settings.validate_runtime_secrets()
