import hashlib
import hmac
import time

import pytest

from backend.integrations.webhook_auth import (
    WebhookAuthenticationError,
    delivery_key,
    github_delivery_key,
    verify_github_webhook,
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


def test_github_webhook_validates_raw_body_signature_and_delivery() -> None:
    body = b'{"action":"submitted"}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    headers = {
        "x-hub-signature-256": signature,
        "x-github-delivery": "delivery-7",
    }
    verify_github_webhook(headers, body, secret="secret")  # noqa: S106
    assert github_delivery_key(headers) == "delivery-7"


def test_github_webhook_rejects_invalid_signature() -> None:
    with pytest.raises(WebhookAuthenticationError, match="signature"):
        verify_github_webhook(  # noqa: S106
            {"x-hub-signature-256": "sha256=wrong"}, b"{}", secret="secret"
        )
