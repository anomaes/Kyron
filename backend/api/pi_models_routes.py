from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from backend.api.admin_routes import require_system_admin
from backend.auth.authorization import audit_event
from backend.auth.dependencies import CurrentUser, DbSession
from backend.config import Settings, get_settings
from backend.db.models import PiModelsConfigRevision, PiModelsConfigState
from backend.engine.pi.models_config import PiModelsConfigError, inspect_models_config
from backend.schemas.pi_models_config import (
    PiModelsCatalogResponse,
    PiModelsConfigAdminResponse,
    PiModelsConfigRequest,
    PiModelsConfigValidationResponse,
)
from backend.services.pi_models_config_service import (
    PiModelsConfigService,
    ResolvedPiModelsConfig,
    catalog_payload,
)

router = APIRouter(tags=["pi models configuration"])


def _service(db: DbSession, settings: Settings) -> PiModelsConfigService:
    return PiModelsConfigService(db, settings)


def _catalog_response(resolved: ResolvedPiModelsConfig) -> PiModelsCatalogResponse:
    document = resolved.document
    required = [] if document is None else sorted(inspect_models_config(document))
    return PiModelsCatalogResponse(
        source=resolved.source,
        revision_id=resolved.revision_id,
        version=resolved.version,
        providers=catalog_payload(document),
        required_credentials=required,
    )


@router.get("/pi/models/catalog", response_model=PiModelsCatalogResponse)
async def models_catalog(
    _: CurrentUser,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PiModelsCatalogResponse:
    try:
        return _catalog_response(await _service(db, settings).resolve())
    except PiModelsConfigError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/admin/pi-models", response_model=PiModelsConfigAdminResponse)
async def admin_models_config(
    user: CurrentUser,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    require_system_admin(user)
    service = _service(db, settings)
    configuration_error = None
    try:
        resolved = await service.resolve()
    except PiModelsConfigError as exc:
        # Keep the admin repair surface available even when the optional file
        # bootstrap is broken. Activating a database revision supersedes that file.
        resolved = ResolvedPiModelsConfig(source="file", document=None)
        configuration_error = str(exc)
    state = await db.get(PiModelsConfigState, 1)
    active_id = state.active_revision_id if state is not None else None
    revisions = await service.revisions()
    return {
        **_catalog_response(resolved).model_dump(),
        "active_revision_id": resolved.revision_id,
        "active_version": resolved.version,
        "document": resolved.document,
        "file_bootstrap_configured": settings.PI_MODELS_CONFIG_PATH is not None,
        "configuration_error": configuration_error,
        "revisions": [
            _revision_payload(revision, revision.id == active_id) for revision in revisions
        ],
    }


@router.post("/admin/pi-models/validate", response_model=PiModelsConfigValidationResponse)
async def validate_admin_models_config(
    request: PiModelsConfigRequest,
    user: CurrentUser,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    require_system_admin(user)
    try:
        providers, required = await _service(db, settings).validate(request.document)
    except PiModelsConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return {"valid": True, "providers": providers, "required_credentials": required}


@router.put("/admin/pi-models", response_model=PiModelsConfigAdminResponse)
async def save_admin_models_config(
    request: PiModelsConfigRequest,
    user: CurrentUser,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    require_system_admin(user)
    service = _service(db, settings)
    try:
        revision = await service.create_and_activate(request.document, user.id)
    except PiModelsConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.add(
        audit_event(
            user,
            "PI_MODELS_CONFIG_ACTIVATED",
            "pi_models_config_revision",
            target_id=str(revision.id),
            details={"version": revision.version, "providers": _provider_ids(revision)},
        )
    )
    await db.commit()
    return await admin_models_config(user, db, settings)


@router.post(
    "/admin/pi-models/revisions/{revision_id}/activate",
    response_model=PiModelsConfigAdminResponse,
)
async def activate_admin_models_revision(
    revision_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    require_system_admin(user)
    service = _service(db, settings)
    try:
        revision = await service.activate(revision_id, user.id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except PiModelsConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.add(
        audit_event(
            user,
            "PI_MODELS_CONFIG_ACTIVATED",
            "pi_models_config_revision",
            target_id=str(revision.id),
            details={"version": revision.version, "providers": _provider_ids(revision)},
        )
    )
    await db.commit()
    return await admin_models_config(user, db, settings)


@router.delete("/admin/pi-models/active", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_admin_models_config(
    user: CurrentUser,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    require_system_admin(user)
    service = _service(db, settings)
    state = await db.get(PiModelsConfigState, 1)
    previous_id = state.active_revision_id if state is not None else None
    await service.deactivate(user.id)
    db.add(
        audit_event(
            user,
            "PI_MODELS_CONFIG_DEACTIVATED",
            "pi_models_config_revision",
            target_id=str(previous_id) if previous_id is not None else None,
            details={
                "fallback": "file" if settings.PI_MODELS_CONFIG_PATH is not None else "builtin"
            },
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _revision_payload(revision: PiModelsConfigRevision, active: bool) -> dict[str, Any]:
    return {
        "id": revision.id,
        "version": revision.version,
        "providers": revision.provider_catalog,
        "required_credentials": revision.required_credentials,
        "created_by": revision.created_by,
        "created_at": revision.created_at,
        "active": active,
    }


def _provider_ids(revision: PiModelsConfigRevision) -> list[str]:
    return [
        item["id"]
        for item in revision.provider_catalog
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
