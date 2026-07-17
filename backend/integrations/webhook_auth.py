from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping


class WebhookAuthenticationError(ValueError):
    pass


def verify_gitlab_webhook(
    headers: Mapping[str, str],
    body: bytes,
    *,
    token_secret: str,
    signing_secret: str = "",
    maximum_age_seconds: int = 300,
) -> None:
    provided_token = headers.get("x-gitlab-token", "")
    if not token_secret or not hmac.compare_digest(provided_token, token_secret):
        raise WebhookAuthenticationError("GitLab webhook token is invalid")
    if not signing_secret:
        return
    webhook_id = headers.get("webhook-id", "")
    timestamp = headers.get("webhook-timestamp", "")
    signature = headers.get("webhook-signature", "")
    try:
        timestamp_number = int(timestamp)
    except ValueError as exc:
        raise WebhookAuthenticationError("GitLab webhook timestamp is invalid") from exc
    if abs(int(time.time()) - timestamp_number) > maximum_age_seconds:
        raise WebhookAuthenticationError("GitLab webhook timestamp is stale")
    signed = webhook_id.encode() + b"." + timestamp.encode() + b"." + body
    expected = hmac.new(signing_secret.encode(), signed, hashlib.sha256).hexdigest()
    normalized = signature.removeprefix("sha256=")
    if not hmac.compare_digest(normalized, expected):
        raise WebhookAuthenticationError("GitLab webhook signature is invalid")


def delivery_key(headers: Mapping[str, str]) -> str:
    if value := headers.get("webhook-id"):
        return value
    if value := headers.get("idempotency-key"):
        return value
    event_uuid = headers.get("x-gitlab-event-uuid", "")
    webhook_uuid = headers.get("x-gitlab-webhook-uuid", "")
    if event_uuid and webhook_uuid:
        return f"{event_uuid}:{webhook_uuid}"
    raise WebhookAuthenticationError("GitLab webhook has no stable delivery identifier")


def verify_github_webhook(headers: Mapping[str, str], body: bytes, *, secret: str) -> None:
    if not secret:
        raise WebhookAuthenticationError("GitHub webhook secret is not configured")
    signature = headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise WebhookAuthenticationError("GitHub webhook signature is invalid")


def github_delivery_key(headers: Mapping[str, str]) -> str:
    value = headers.get("x-github-delivery", "")
    if not value:
        raise WebhookAuthenticationError("GitHub webhook has no delivery identifier")
    return value
