from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from backend.auth.dependencies import DbSession
from backend.config import Settings, get_settings
from backend.db.models import Project
from backend.db.repositories.webhooks import WebhookDeliveryRepository
from backend.dependencies import Cipher
from backend.engine.process_registry import process_registry
from backend.integrations.code_host import create_code_host_client
from backend.integrations.git_manager import GitManager
from backend.integrations.github_webhooks import route_github_event
from backend.integrations.gitlab_webhooks import route_gitlab_event
from backend.integrations.webhook_auth import (
    WebhookAuthenticationError,
    delivery_key,
    github_delivery_key,
    verify_github_webhook,
    verify_gitlab_webhook,
)
from backend.lifecycle import runtime
from backend.services.cleanup_service import CleanupService
from backend.services.feedback_service import FeedbackService

router = APIRouter(prefix="/webhook", tags=["webhooks"])
MAX_WEBHOOK_BODY_BYTES = 2 * 1024 * 1024


async def _webhook_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "Webhook body is too large",
            )
        body.extend(chunk)
    return bytes(body)


def _payload_project_id(provider: str, payload: dict[str, Any]) -> str | None:
    container = payload.get("project") if provider == "gitlab" else payload.get("repository")
    provider_project_id = (container or {}).get("id")
    return str(provider_project_id) if isinstance(provider_project_id, int) else None


async def _webhook_project(
    db: DbSession,
    provider: str,
    payload: dict[str, Any],
) -> Project:
    provider_project_id = _payload_project_id(provider, payload)
    project: Project | None = (
        await db.scalar(
            select(Project).where(
                Project.provider == provider,
                Project.provider_project_id == provider_project_id,
            )
        )
        if provider_project_id is not None
        else None
    )
    if project is None or project.encrypted_webhook_secret is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Webhook authentication failed",
        )
    return project


def _webhook_payload(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Webhook body is too large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Webhook JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Webhook JSON must be an object")
    return payload


@router.post("/gitlab")
async def gitlab_webhook(
    request: Request,
    db: DbSession,
    cipher: Cipher,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    raw = await _webhook_body(request)
    headers = {key.lower(): value for key, value in request.headers.items()}
    payload = _webhook_payload(raw)
    project = await _webhook_project(db, "gitlab", payload)
    assert project.encrypted_webhook_secret is not None
    try:
        verify_gitlab_webhook(
            headers,
            raw,
            token_secret=cipher.decrypt(project.encrypted_webhook_secret),
            signing_secret=(
                cipher.decrypt(project.encrypted_webhook_signing_secret)
                if project.encrypted_webhook_signing_secret is not None
                else ""
            ),
        )
        key = delivery_key(headers)
    except WebhookAuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    repository = WebhookDeliveryRepository(db)
    reservation = await repository.try_begin(
        "gitlab",
        key,
        headers.get("x-gitlab-event", "unknown"),
        provider_project_id=project.provider_project_id,
    )
    delivery_id = reservation.delivery.id
    await db.commit()
    if not reservation.created:
        return reservation.delivery.result or {"status": "duplicate"}
    try:
        code_host = create_code_host_client("gitlab", settings)
        git = GitManager(
            settings.PROJECT_CLONE_BASE_PATH,
            settings.WORKTREE_BASE_PATH,
            settings.RUN_DATA_BASE_PATH,
        )
        try:
            result = await route_gitlab_event(
                db,
                payload,
                FeedbackService(db, cipher, code_host, runtime.schedule),
                CleanupService(
                    db,
                    git,
                    process_registry,
                    runtime.tasks,
                    settings.PROCESS_TERMINATION_GRACE_SECONDS,
                ),
            )
        finally:
            await code_host.close()
        await repository.finish(delivery_id, "PROCESSED", result)
        await db.commit()
        return result
    except Exception as exc:
        result = {"status": "failed", "reason": str(exc)}
        await repository.finish(delivery_id, "FAILED", result)
        await db.commit()
        raise


@router.post("/github")
async def github_webhook(
    request: Request,
    db: DbSession,
    cipher: Cipher,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    raw = await _webhook_body(request)
    headers = {key.lower(): value for key, value in request.headers.items()}
    payload = _webhook_payload(raw)
    project = await _webhook_project(db, "github", payload)
    assert project.encrypted_webhook_secret is not None
    try:
        verify_github_webhook(
            headers,
            raw,
            secret=cipher.decrypt(project.encrypted_webhook_secret),
        )
        key = github_delivery_key(headers)
    except WebhookAuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    event_name = headers.get("x-github-event", "unknown")
    repository = WebhookDeliveryRepository(db)
    reservation = await repository.try_begin(
        "github",
        key,
        event_name,
        provider_project_id=project.provider_project_id,
    )
    delivery_id = reservation.delivery.id
    await db.commit()
    if not reservation.created:
        return reservation.delivery.result or {"status": "duplicate"}
    try:
        code_host = create_code_host_client("github", settings)
        git = GitManager(
            settings.PROJECT_CLONE_BASE_PATH,
            settings.WORKTREE_BASE_PATH,
            settings.RUN_DATA_BASE_PATH,
        )
        try:
            result = await route_github_event(
                db,
                event_name,
                payload,
                FeedbackService(db, cipher, code_host, runtime.schedule),
                CleanupService(
                    db,
                    git,
                    process_registry,
                    runtime.tasks,
                    settings.PROCESS_TERMINATION_GRACE_SECONDS,
                ),
            )
        finally:
            await code_host.close()
        await repository.finish(delivery_id, "PROCESSED", result)
        await db.commit()
        return result
    except Exception as exc:
        result = {"status": "failed", "reason": str(exc)}
        await repository.finish(delivery_id, "FAILED", result)
        await db.commit()
        raise
