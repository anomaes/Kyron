import hashlib
import hmac
import time

import pytest

from backend.integrations.webhook_auth import (
    WebhookAuthenticationError,
    delivery_key,
    verify_gitlab_webhook,
)


def test_token_and_optional_signature_are_verified() -> None:
    body = b'{"event":"test"}'
    timestamp = str(int(time.time()))
    signed = b"delivery-1." + timestamp.encode() + b"." + body
    signature = hmac.new(b"signing", signed, hashlib.sha256).hexdigest()
    headers = {
        "x-gitlab-token": "token",
        "webhook-id": "delivery-1",
        "webhook-timestamp": timestamp,
        "webhook-signature": f"sha256={signature}",
    }
    verify_gitlab_webhook(  # noqa: S106
        headers, body, token_secret="token", signing_secret="signing"
    )
    assert delivery_key(headers) == "delivery-1"


def test_invalid_token_and_missing_delivery_id_fail_closed() -> None:
    with pytest.raises(WebhookAuthenticationError, match="token"):
        verify_gitlab_webhook(  # noqa: S106
            {"x-gitlab-token": "wrong"}, b"{}", token_secret="correct"
        )
    with pytest.raises(WebhookAuthenticationError, match="delivery"):
        delivery_key({})
