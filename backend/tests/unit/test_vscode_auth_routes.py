from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import cast

from backend.api.vscode_auth_routes import show_device_authorization
from backend.auth.dependencies import AuthenticatedUser
from backend.db.models import VsCodeDeviceAuthorization
from backend.services.vscode_auth_service import VsCodeAuthService


class PendingDeviceService:
    async def get_pending_device(self, user_code: str) -> VsCodeDeviceAuthorization:
        assert user_code == "ABCD-EFGH"
        return cast(
            VsCodeDeviceAuthorization,
            SimpleNamespace(user_code="ABCD-EFGH"),
        )


async def test_authorization_form_preserves_public_path_prefix() -> None:
    user = AuthenticatedUser(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Kyron User",
        avatar_url=None,
        provider="github",
        provider_user_id="7",
        provider_username="kyron-user",
    )

    response = await show_device_authorization(
        user,
        cast(VsCodeAuthService, PendingDeviceService()),
        "ABCD-EFGH",
    )
    body = bytes(response.body).decode("utf-8")

    assert 'action="?user_code=ABCD-EFGH"' in body
    assert 'action="/api/auth/vscode/authorize' not in body
