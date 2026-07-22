from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.types import Message, Scope

from backend.api import webhook_routes
from backend.config import Settings
from backend.db.models import WebhookDelivery
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


@pytest.mark.parametrize("provider", ["gitlab", "github"])
async def test_failure_handler_uses_delivery_id_captured_before_rollback(
    provider: str,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b'{"project":{"id":123},"repository":{"id":456}}'
    settings = Settings(
        GITLAB_WEBHOOK_SECRET="webhook-secret",
        GITHUB_WEBHOOK_SECRET="webhook-secret",
        _env_file=None,
    )
    cipher = SecretCipher(Fernet.generate_key())

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
        select(WebhookDelivery).where(
            WebhookDelivery.delivery_key == f"{provider}:delivery-1"
        )
    )
    assert delivery is not None
    assert delivery.status == "FAILED"
    assert delivery.result == {"status": "failed", "reason": "feedback failed"}
