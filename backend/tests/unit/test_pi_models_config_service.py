from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import backend.services.pi_models_config_service as service_module
from backend.config import Settings
from backend.db.models import PiModelsConfigRevision, User
from backend.engine.pi.models_config import PiModelsConfigError
from backend.services.pi_models_config_service import PiModelsConfigService

DOCUMENT = {
    "providers": {
        "external-gateway": {
            "baseUrl": "https://llm.example.com/v1",
            "api": "openai-completions",
            "apiKey": "$BEARER_TOKEN",
            "authHeader": True,
            "headers": {"x-api-key": "$GATEWAY_API_KEY"},
            "models": [{"id": "example-model"}],
        }
    }
}


async def accept_document(_: object) -> None:
    pass


async def test_revision_activation_and_rollback_preserve_auth_metadata(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_module, "validate_models_document", accept_document)
    user = User(email="admin@example.com", display_name="Admin", is_system_admin=True)
    db_session.add(user)
    await db_session.flush()
    service = PiModelsConfigService(db_session, Settings(_env_file=None))

    first = await service.create_and_activate(DOCUMENT, user.id)
    second_document = {
        "providers": {
            "ollama": {
                "baseUrl": "http://ollama.ollama.svc.cluster.local:11434/v1",
                "api": "openai-completions",
                "apiKey": "$OLLAMA_API_KEY",
                "models": [{"id": "qwen2.5-coder:7b"}],
            }
        }
    }
    second = await service.create_and_activate(second_document, user.id)
    await db_session.commit()

    assert (first.version, second.version) == (1, 2)
    assert first.required_credentials == ["BEARER_TOKEN", "GATEWAY_API_KEY"]
    assert first.provider_catalog == [
        {
            "id": "external-gateway",
            "models": ["example-model"],
            "required_credentials": ["BEARER_TOKEN", "GATEWAY_API_KEY"],
        }
    ]
    assert (await service.resolve()).revision_id == second.id

    await service.activate(first.id, user.id)
    await db_session.commit()
    restored = await service.resolve()
    assert restored.revision_id == first.id
    assert restored.document == DOCUMENT

    await service.deactivate(user.id)
    await db_session.commit()
    assert (await service.resolve()).source == "builtin"
    assert len(list(await db_session.scalars(select(PiModelsConfigRevision)))) == 2


async def test_file_is_only_used_as_optional_fallback(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_module, "validate_models_document", accept_document)
    source = tmp_path / "models.json"
    source.write_text(json.dumps(DOCUMENT), encoding="utf-8")
    user = User(email="admin-file@example.com", display_name="Admin")
    db_session.add(user)
    await db_session.flush()
    service = PiModelsConfigService(
        db_session, Settings(_env_file=None, PI_MODELS_CONFIG_PATH=source)
    )

    fallback = await service.resolve()
    assert fallback.source == "file"
    assert fallback.document == DOCUMENT

    revision = await service.create_and_activate(
        {"providers": {"database-provider": {"baseUrl": "https://db.example/v1"}}},
        user.id,
    )
    await db_session.commit()
    active = await service.resolve()
    assert active.source == "database"
    assert active.revision_id == revision.id


async def test_inline_header_secrets_are_rejected_before_activation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    async def validator(_: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(service_module, "validate_models_document", validator)
    service = PiModelsConfigService(db_session, Settings(_env_file=None))

    with pytest.raises(PiModelsConfigError, match="inline secret"):
        await service.validate(
            {
                "providers": {
                    "unsafe": {
                        "baseUrl": "https://llm.example/v1",
                        "api": "openai-completions",
                        "headers": {"x-api-key": "plaintext"},
                        "models": [{"id": "model"}],
                    }
                }
            }
        )

    assert not called
