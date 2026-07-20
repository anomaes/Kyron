import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from backend.auth.authorization import (
    PROJECT_MANAGE,
    PROJECT_VIEW,
    accessible_project_ids,
    audit_event,
    authorize_project,
)
from backend.auth.dependencies import CurrentUser, DbSession, require_project_provider
from backend.config import Settings, get_settings
from backend.dependencies import Cipher
from backend.integrations.code_host import CodeHostError, provider_display_name
from backend.integrations.git_manager import GitManager
from backend.schemas.pi import PiSettings
from backend.schemas.project import (
    ProjectCreate,
    ProjectResponse,
    ProjectTokenUpdate,
    ProjectValidationResponse,
)
from backend.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


async def get_project_service(
    db: DbSession,
    cipher: Cipher,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProjectService:
    return ProjectService(
        db,
        settings,
        cipher,
        GitManager(
            settings.PROJECT_CLONE_BASE_PATH,
            settings.WORKTREE_BASE_PATH,
            settings.RUN_DATA_BASE_PATH,
        ),
    )


ProjectServiceDependency = Annotated[
    ProjectService,
    Depends(get_project_service),
]


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    user: CurrentUser, db: DbSession, project_service: ProjectServiceDependency
) -> list[ProjectResponse]:
    allowed = await accessible_project_ids(db, user)
    projects = await project_service.list()
    if allowed is not None:
        allowed_set = set(allowed)
        projects = [project for project in projects if project.id in allowed_set]
    return [ProjectResponse.model_validate(item) for item in projects]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def register_project(
    request: ProjectCreate,
    user: CurrentUser,
    db: DbSession,
    project_service: ProjectServiceDependency,
) -> ProjectResponse:
    try:
        if not user.is_system_admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only a system administrator may register projects"
            )
        if request.provider != user.provider:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Sign in with {provider_display_name(request.provider)} to register this project",
            )
        project = await project_service.register(request, user.id)
        db.add(
            audit_event(
                user,
                "PROJECT_REGISTERED",
                "project",
                project_id=project.id,
                target_id=str(project.id),
            )
        )
    except (CodeHostError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    project_service: ProjectServiceDependency,
) -> ProjectResponse:
    try:
        await authorize_project(db, user, project_id, PROJECT_VIEW)
        return ProjectResponse.model_validate(await project_service.get(project_id))
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.put("/{project_id}/token", response_model=ProjectResponse)
async def replace_project_token(
    project_id: uuid.UUID,
    request: ProjectTokenUpdate,
    user: CurrentUser,
    db: DbSession,
    project_service: ProjectServiceDependency,
) -> ProjectResponse:
    try:
        existing = await project_service.get(project_id)
        require_project_provider(user, existing.provider)
        await authorize_project(db, user, project_id, PROJECT_MANAGE)
        project = await project_service.replace_token(project_id, request.access_token)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.add(
        audit_event(
            user,
            "PROJECT_TOKEN_REPLACED",
            "project",
            project_id=project_id,
            target_id=str(project_id),
        )
    )
    await db.commit()
    return ProjectResponse.model_validate(project)


@router.put("/{project_id}/pi", response_model=ProjectResponse)
async def update_project_pi(
    project_id: uuid.UUID,
    request: PiSettings,
    user: CurrentUser,
    db: DbSession,
    project_service: ProjectServiceDependency,
) -> ProjectResponse:
    try:
        existing = await project_service.get(project_id)
        require_project_provider(user, existing.provider)
        await authorize_project(db, user, project_id, PROJECT_MANAGE)
        project = await project_service.update_pi(project_id, request)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.add(
        audit_event(
            user,
            "PROJECT_PI_DEFAULTS_UPDATED",
            "project",
            project_id=project_id,
            target_id=str(project_id),
        )
    )
    await db.commit()
    return ProjectResponse.model_validate(project)


@router.post("/{project_id}/fetch")
async def fetch_project(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    project_service: ProjectServiceDependency,
) -> dict[str, str]:
    try:
        project = await project_service.get(project_id)
        require_project_provider(user, project.provider)
        await authorize_project(db, user, project_id, PROJECT_MANAGE)
        return {"commit_sha": await project_service.fetch(project_id)}
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/{project_id}/validate", response_model=ProjectValidationResponse)
async def validate_project(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    project_service: ProjectServiceDependency,
) -> ProjectValidationResponse:
    try:
        project = await project_service.get(project_id)
        require_project_provider(user, project.provider)
        await authorize_project(db, user, project_id, PROJECT_MANAGE)
        result = await project_service.validate(project_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return ProjectValidationResponse.model_validate(result)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    project_service: ProjectServiceDependency,
) -> Response:
    try:
        project = await project_service.get(project_id)
        require_project_provider(user, project.provider)
        await authorize_project(db, user, project_id, PROJECT_MANAGE)
        await project_service.delete(project_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
