from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=True
    )

    APP_ENV: str = "development"
    APP_BASE_URL: HttpUrl = HttpUrl("http://localhost")
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "sqlite+aiosqlite:///./kyron.db"
    DB_POOL_SIZE: int = Field(20, ge=1)
    DB_MAX_OVERFLOW: int = Field(10, ge=0)

    CREDENTIALS_ENCRYPTION_KEY: str = ""
    CREDENTIALS_ENCRYPTION_KEY_VERSION: int = Field(1, ge=1)

    GITLAB_URL: HttpUrl = HttpUrl("https://gitlab.com")
    GITLAB_OAUTH_CLIENT_ID: str = ""
    GITLAB_WEBHOOK_SECRET: str = ""
    GITLAB_WEBHOOK_SIGNING_SECRET: str = ""
    GITHUB_API_URL: HttpUrl = HttpUrl("https://api.github.com")
    GITHUB_OAUTH_CLIENT_ID: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""

    PROJECT_CLONE_BASE_PATH: Path = Path("/var/workflowengine/repos")
    WORKTREE_BASE_PATH: Path = Path("/var/workflowengine/worktrees")
    RUN_DATA_BASE_PATH: Path = Path("/var/workflowengine/run_data")

    MAX_CONCURRENT_RUNS: int = Field(10, ge=1)
    DEFAULT_NODE_TIMEOUT_SECONDS: int = Field(1800, ge=1)
    MAX_NODE_TIMEOUT_SECONDS: int = Field(14400, ge=1)
    MAX_REVIEW_ITERATIONS: int = Field(10, ge=1)
    MAX_SUBWORKFLOW_DEPTH: int = Field(8, ge=1)
    MAX_OUTPUT_VARIABLE_BYTES: int = Field(65536, ge=1024)
    PROCESS_TERMINATION_GRACE_SECONDS: float = Field(10, ge=0)
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

    @field_validator("MAX_NODE_TIMEOUT_SECONDS")
    @classmethod
    def max_timeout_covers_default(cls, value: int, info: object) -> int:
        data = getattr(info, "data", {})
        if value < data.get("DEFAULT_NODE_TIMEOUT_SECONDS", 0):
            raise ValueError("MAX_NODE_TIMEOUT_SECONDS must cover the default timeout")
        return value

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    def validate_runtime_secrets(self) -> None:
        if self.is_production and not self.CREDENTIALS_ENCRYPTION_KEY:
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY is required in production")
        if self.is_production and self.GITLAB_OAUTH_CLIENT_ID and not self.GITLAB_WEBHOOK_SECRET:
            raise ValueError("GITLAB_WEBHOOK_SECRET is required in production")
        if self.is_production and self.GITHUB_OAUTH_CLIENT_ID and not self.GITHUB_WEBHOOK_SECRET:
            raise ValueError("GITHUB_WEBHOOK_SECRET is required in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
