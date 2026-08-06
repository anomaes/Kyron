from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import backend.services.pi_models_config_service as service_module
from backend.api.pi_models_routes import admin_models_config, save_admin_models_config
from backend.auth.dependencies import AuthenticatedUser
from backend.config import Settings
from backend.db.models import AuthorizationAuditEvent, User
from backend.schemas.pi_models_config import PiModelsConfigRequest


async def accept_document(_: object) -> None:
    pass


def authenticated(user: User, *, admin: bool) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=None,
        provider="github",
        provider_user_id="1",
        provider_username="admin",
        is_system_admin=admin,
    )


async def test_only_system_admin_can_activate_provider_configuration(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_module, "validate_models_document", accept_document)
    user = User(email="user@example.com", display_name="User")
    db_session.add(user)
    await db_session.flush()
    request = PiModelsConfigRequest(document={"providers": {}})

    with pytest.raises(HTTPException) as failure:
        await save_admin_models_config(
            request, authenticated(user, admin=False), db_session, Settings(_env_file=None)
        )

    assert failure.value.status_code == 403


async def test_activation_is_audited_without_configuration_values(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_module, "validate_models_document", accept_document)
    user = User(email="admin@example.com", display_name="Admin", is_system_admin=True)
    db_session.add(user)
    await db_session.flush()
    request = PiModelsConfigRequest(
        document={
            "providers": {
                "external": {
                    "baseUrl": "https://llm.example/v1",
                    "api": "openai-completions",
                    "headers": {"x-api-key": "$EXTERNAL_API_KEY"},
                    "models": [{"id": "model"}],
                }
            }
        }
    )

    response = await save_admin_models_config(
        request, authenticated(user, admin=True), db_session, Settings(_env_file=None)
    )
    events = list(await db_session.scalars(select(AuthorizationAuditEvent)))

    assert response["active_version"] == 1
    assert response["required_credentials"] == ["EXTERNAL_API_KEY"]
    assert len(events) == 1
    assert events[0].action == "PI_MODELS_CONFIG_ACTIVATED"
    assert events[0].details == {"version": 1, "providers": ["external"]}


async def test_admin_repair_surface_survives_a_broken_optional_file(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user = User(email="repair@example.com", display_name="Repair", is_system_admin=True)
    db_session.add(user)
    await db_session.flush()
    missing = tmp_path / "missing-models.json"

    response = await admin_models_config(
        authenticated(user, admin=True),
        db_session,
        Settings(_env_file=None, PI_MODELS_CONFIG_PATH=missing),
    )

    assert response["source"] == "file"
    assert response["document"] is None
    assert "Cannot read" in response["configuration_error"]
