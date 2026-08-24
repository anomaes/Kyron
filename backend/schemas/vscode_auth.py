from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class VsCodeDeviceResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class VsCodeTokenRequest(BaseModel):
    grant_type: Literal["device_code", "refresh_token"]
    device_code: str | None = Field(default=None, min_length=20)
    refresh_token: str | None = Field(default=None, min_length=20)

    @model_validator(mode="after")
    def matching_credential(self) -> VsCodeTokenRequest:
        if self.grant_type == "device_code" and not self.device_code:
            raise ValueError("device_code is required for the device_code grant")
        if self.grant_type == "refresh_token" and not self.refresh_token:
            raise ValueError("refresh_token is required for the refresh_token grant")
        return self


class VsCodeTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int


class VsCodeRevokeRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class VsCodeTokenIdentity(BaseModel):
    email: str
    display_name: str
    avatar_url: str | None
    provider: str
    provider_user_id: str
    provider_username: str
