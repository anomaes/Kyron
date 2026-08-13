from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.config import Settings


def test_default_configuration_is_development() -> None:
    settings = Settings(_env_file=None)
    assert settings.APP_ENV == "development"
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


def test_pi_models_config_path_is_optional_and_must_be_absolute() -> None:
    assert Settings(_env_file=None).PI_MODELS_CONFIG_PATH is None
    assert Settings(PI_MODELS_CONFIG_PATH="", _env_file=None).PI_MODELS_CONFIG_PATH is None
    configured = Settings(
        PI_MODELS_CONFIG_PATH="/var/workflowengine/pi/models.json", _env_file=None
    )
    assert configured.PI_MODELS_CONFIG_PATH == Path("/var/workflowengine/pi/models.json")
    with pytest.raises(ValidationError, match="absolute path"):
        Settings(PI_MODELS_CONFIG_PATH="pi/models.json", _env_file=None)


def test_unknown_backend_settings_are_rejected_but_shared_env_keys_are_allowed(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "valid.env"
    valid.write_text("APP_HOST=example.test\nPOSTGRES_PASSWORD=shared\n")
    assert Settings(_env_file=valid).APP_ENV == "development"

    invalid = tmp_path / "invalid.env"
    invalid.write_text("MAX_CONCURENT_RUNS=99\n")
    with pytest.raises(ValidationError, match="MAX_CONCURENT_RUNS"):
        Settings(_env_file=invalid)
