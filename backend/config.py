from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

SHARED_ENV_KEYS = {
    "APP_HOST",
    "GITHUB_OAUTH_CLIENT_ID",
    "GITHUB_OAUTH_CLIENT_SECRET",
    "GITHUB_WEBHOOK_SECRET",
    "GITHUB_WEB_URL",
    "GITLAB_OAUTH_CLIENT_ID",
    "GITLAB_OAUTH_CLIENT_SECRET",
    "GITLAB_WEBHOOK_SECRET",
    "GITLAB_WEBHOOK_SIGNING_SECRET",
    "OAUTH_REDIRECT_URI",
    "PI_VERSION",
    "POSTGRES_PASSWORD",
    "SESSION_MAX_AGE_SECONDS",
    "SESSION_PREVIOUS_SIGNING_KEY",
    "SESSION_SIGNING_KEY",
    "WORKFLOW_DATA_HOST_PATH",
}


class SharedEnvDotEnvSettingsSource(DotEnvSettingsSource):
    def __call__(self) -> dict[str, Any]:
        values = super().__call__()
        for key in SHARED_ENV_KEYS:
            values.pop(key, None)
        return values


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="forbid", case_sensitive=True
    )

    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "sqlite+aiosqlite:///./kyron.db"
    DB_POOL_SIZE: int = Field(20, ge=1)
    DB_MAX_OVERFLOW: int = Field(10, ge=0)

    CREDENTIALS_ENCRYPTION_KEY: str = ""
    CREDENTIALS_ENCRYPTION_KEY_VERSION: int = Field(1, ge=1)

    GITLAB_URL: HttpUrl = HttpUrl("https://gitlab.com")
    GITHUB_API_URL: HttpUrl = HttpUrl("https://api.github.com")

    PROJECT_CLONE_BASE_PATH: Path = Path("/var/workflowengine/repos")
    WORKTREE_BASE_PATH: Path = Path("/var/workflowengine/worktrees")
    RUN_DATA_BASE_PATH: Path = Path("/var/workflowengine/run_data")
    PI_MODELS_CONFIG_PATH: Path | None = None

    MAX_CONCURRENT_RUNS: int = Field(10, ge=1)
    MAX_NODE_TIMEOUT_SECONDS: int = Field(14400, ge=1)
    MAX_REVIEW_ITERATIONS: int = Field(10, ge=1)
    MAX_SUBWORKFLOW_DEPTH: int = Field(8, ge=1)
    MAX_OUTPUT_VARIABLE_BYTES: int = Field(65536, ge=1024)
    PROCESS_TERMINATION_GRACE_SECONDS: float = Field(10, ge=0)
    PROCESS_STREAM_DRAIN_TIMEOUT_SECONDS: float = Field(30, gt=0)
    MAX_ATTEMPT_OUTPUT_BYTES: int = Field(100 * 1024**2, ge=1024)
    QUEUE_RECONCILIATION_INTERVAL_SECONDS: int = Field(60, ge=1)
    STALE_RESOURCE_RECONCILIATION_INTERVAL_SECONDS: int = Field(3600, ge=60)
    STALE_FAILED_RUN_DAYS: int = Field(7, ge=1)
    TERMINAL_WORKTREE_RETENTION_DAYS: int = Field(1, ge=0)
    ORPHAN_WORKTREE_GRACE_HOURS: int = Field(24, ge=1)
    RUN_OUTPUT_RETENTION_DAYS: int = Field(30, ge=1)
    LONG_OPEN_CHANGE_REQUEST_WARNING_DAYS: int = Field(14, ge=1)
    LONG_OPEN_CHANGE_REQUEST_WARNING_REPEAT_DAYS: int = Field(7, ge=1)
    WORKTREE_USAGE_WARNING_BYTES: int = Field(50 * 1024**3, ge=0)
    RUN_DATA_USAGE_WARNING_BYTES: int = Field(50 * 1024**3, ge=0)
    FILESYSTEM_USAGE_WARNING_PERCENT: int = Field(85, ge=1, le=100)
    AUTH_USER_TOUCH_INTERVAL_SECONDS: int = Field(300, ge=0)
    VSCODE_DEVICE_CODE_TTL_SECONDS: int = Field(600, ge=60, le=1800)
    VSCODE_DEVICE_POLL_INTERVAL_SECONDS: int = Field(3, ge=1, le=30)
    VSCODE_ACCESS_TOKEN_TTL_SECONDS: int = Field(900, ge=60, le=86400)
    VSCODE_REFRESH_TOKEN_TTL_DAYS: int = Field(30, ge=1, le=365)
    WORKFLOW_CATALOG_CACHE_TTL_SECONDS: int = Field(30, ge=0)

    @field_validator("LOG_LEVEL")
    @classmethod
    def valid_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("LOG_LEVEL must be CRITICAL, ERROR, WARNING, INFO, or DEBUG")
        return normalized

    @field_validator("PI_MODELS_CONFIG_PATH", mode="before")
    @classmethod
    def optional_absolute_path(cls, value: Any) -> Any:
        # An unset key in .env arrives as "", which would otherwise become Path(".").
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not Path(value).is_absolute():
            raise ValueError("PI_MODELS_CONFIG_PATH must be an absolute path")
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        assert isinstance(dotenv_settings, DotEnvSettingsSource)
        shared_dotenv = SharedEnvDotEnvSettingsSource(
            settings_cls,
            env_file=dotenv_settings.env_file,
            env_file_encoding=dotenv_settings.env_file_encoding,
        )
        return init_settings, env_settings, shared_dotenv, file_secret_settings

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    def validate_runtime_secrets(self) -> None:
        if self.is_production and not self.CREDENTIALS_ENCRYPTION_KEY:
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY is required in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
