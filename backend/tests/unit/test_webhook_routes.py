from __future__ import annotations

import hashlib
import hmac
import uuid
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.types import Message, Scope

from backend.api import webhook_routes
from backend.config import Settings
from backend.db.models import Project, User, WebhookDelivery
from backend.services.crypto import SecretCipher


class StubCodeHost:
    async def close(self) -> None:
        return None


def webhook_request(body: bytes, headers: dict[str, str]) -> Request:
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
    }

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


async def test_webhook_body_size_is_limited_before_json_parsing() -> None:
    body = b"x" * (webhook_routes.MAX_WEBHOOK_BODY_BYTES + 1)

    with pytest.raises(HTTPException) as exc_info:
        await webhook_routes._webhook_body(webhook_request(body, {}))

    assert exc_info.value.status_code == 413


@pytest.mark.parametrize("provider", ["gitlab", "github"])
async def test_failure_handler_uses_delivery_id_captured_before_rollback(
    provider: str,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    body = b'{"project":{"id":123},"repository":{"id":456}}'
    cipher = SecretCipher(Fernet.generate_key())
    settings = Settings(CREDENTIALS_ENCRYPTION_KEY=Fernet.generate_key().decode(), _env_file=None)
    provider_project_id = "123" if provider == "gitlab" else "456"
    user = User(id=uuid.uuid4(), email=f"{provider}@example.com", display_name=provider)
    project = Project(
        id=uuid.uuid4(),
        name=f"{provider} project",
        git_url=f"https://{provider}.example/acme/project.git",
        provider=provider,
        provider_project_id=provider_project_id,
        provider_project_path="acme/project",
        encrypted_access_token=b"unused",
        encrypted_webhook_secret=cipher.encrypt("webhook-secret"),
        webhook_secret_key_version=cipher.key_version,
        local_path=str(tmp_path / provider_project_id),
        default_branch="main",
        added_by=user.id,
    )
    db_session.add_all([user, project])
    await db_session.commit()

    async def fail_after_rollback(session: AsyncSession, *_: Any) -> dict[str, Any]:
        await session.execute(select(WebhookDelivery))
        await session.rollback()
        raise RuntimeError("feedback failed")

    monkeypatch.setattr(webhook_routes, "create_code_host_client", lambda *_: StubCodeHost())
    if provider == "gitlab":
        headers = {
            "x-gitlab-token": "webhook-secret",
            "webhook-id": "delivery-1",
            "x-gitlab-event": "Merge Request Hook",
        }
        monkeypatch.setattr(webhook_routes, "route_gitlab_event", fail_after_rollback)
        handle = webhook_routes.gitlab_webhook
    else:
        signature = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
        headers = {
            "x-hub-signature-256": f"sha256={signature}",
            "x-github-delivery": "delivery-1",
            "x-github-event": "pull_request_review",
        }
        monkeypatch.setattr(webhook_routes, "route_github_event", fail_after_rollback)
        handle = webhook_routes.github_webhook

    with pytest.raises(RuntimeError, match="feedback failed"):
        await handle(webhook_request(body, headers), db_session, cipher, settings)

    delivery = await db_session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.delivery_key == f"{provider}:delivery-1")
    )
    assert delivery is not None
    assert delivery.status == "FAILED"
    assert delivery.result == {"status": "failed", "reason": "feedback failed"}


async def test_github_webhook_uses_the_target_projects_secret(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    user = User(id=uuid.uuid4(), email="owner@example.com", display_name="Owner")
    project = Project(
        id=uuid.uuid4(),
        name="Target",
        git_url="https://github.example/acme/target.git",
        provider="github",
        provider_project_id="456",
        provider_project_path="acme/target",
        encrypted_access_token=b"unused",
        encrypted_webhook_secret=cipher.encrypt("target-project-secret"),
        webhook_secret_key_version=cipher.key_version,
        local_path=str(tmp_path / "target-project"),
        default_branch="main",
        added_by=user.id,
    )
    db_session.add_all([user, project])
    await db_session.commit()
    body = b'{"repository":{"id":456}}'
    wrong_signature = hmac.new(b"another-project-secret", body, hashlib.sha256).hexdigest()

    with pytest.raises(HTTPException) as exc_info:
        await webhook_routes.github_webhook(
            webhook_request(
                body,
                {
                    "x-hub-signature-256": f"sha256={wrong_signature}",
                    "x-github-delivery": "wrong-project-secret",
                },
            ),
            db_session,
            cipher,
            Settings(_env_file=None),
        )

    assert exc_info.value.status_code == 401
