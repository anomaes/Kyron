from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PiSettings(BaseModel):
    """Defaults for Pi prompt-node invocations at a configuration scope."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, min_length=1, max_length=255)
    model: str | None = Field(default=None, min_length=1, max_length=512)
    skill: str | None = Field(default=None, min_length=1, max_length=1024)

    @field_validator("skill")
    @classmethod
    def skill_must_be_relative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Pi skill path must remain inside the repository")
        return value
