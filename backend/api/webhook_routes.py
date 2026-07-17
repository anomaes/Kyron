from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.auth.dependencies import DbSession
from backend.config import Settings, get_settings
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


@router.post("/gitlab")
async def gitlab_webhook(
    request: Request,
    db: DbSession,
    cipher: Cipher,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    raw = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    try:
        verify_gitlab_webhook(
            headers,
            raw,
            token_secret=settings.GITLAB_WEBHOOK_SECRET,
            signing_secret=settings.GITLAB_WEBHOOK_SIGNING_SECRET,
        )
        key = delivery_key(headers)
    except WebhookAuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    repository = WebhookDeliveryRepository(db)
    reservation = await repository.try_begin(
        "gitlab", key, headers.get("x-gitlab-event", "unknown")
    )
    await db.commit()
    if not reservation.created:
        return reservation.delivery.result or {"status": "duplicate"}
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Webhook JSON must be an object")
        project_id = (payload.get("project") or {}).get("id")
        if isinstance(project_id, int):
            reservation.delivery.provider_project_id = str(project_id)
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
        await repository.finish(reservation.delivery.id, "PROCESSED", result)
        await db.commit()
        return result
    except Exception as exc:
        result = {"status": "failed", "reason": str(exc)}
        await repository.finish(reservation.delivery.id, "FAILED", result)
        await db.commit()
        raise


@router.post("/github")
async def github_webhook(
    request: Request,
    db: DbSession,
    cipher: Cipher,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    raw = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    try:
        verify_github_webhook(headers, raw, secret=settings.GITHUB_WEBHOOK_SECRET)
        key = github_delivery_key(headers)
    except WebhookAuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    event_name = headers.get("x-github-event", "unknown")
    repository = WebhookDeliveryRepository(db)
    reservation = await repository.try_begin("github", key, event_name)
    await db.commit()
    if not reservation.created:
        return reservation.delivery.result or {"status": "duplicate"}
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Webhook JSON must be an object")
        repository_id = (payload.get("repository") or {}).get("id")
        if isinstance(repository_id, int):
            reservation.delivery.provider_project_id = str(repository_id)
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
        await repository.finish(reservation.delivery.id, "PROCESSED", result)
        await db.commit()
        return result
    except Exception as exc:
        result = {"status": "failed", "reason": str(exc)}
        await repository.finish(reservation.delivery.id, "FAILED", result)
        await db.commit()
        raise
