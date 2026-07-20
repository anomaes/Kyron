import uuid

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    avatar_url: str | None
    provider: str
    provider_user_id: str
    provider_username: str
    is_system_admin: bool
