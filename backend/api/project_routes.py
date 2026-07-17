import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from backend.auth.dependencies import CurrentUser, DbSession
from backend.config import Settings, get_settings
from backend.dependencies import Cipher
from backend.integrations.git_manager import GitManager
from backend.integrations.gitlab_client import GitLabClient, GitLabError
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
) -> AsyncIterator[ProjectService]:
    gitlab = GitLabClient(str(settings.GITLAB_URL))
    try:
        yield ProjectService(
            db,
            cipher,
            GitManager(settings.PROJECT_CLONE_BASE_PATH),
            gitlab,
        )
    finally:
        await gitlab.close()


ProjectServiceDependency = Annotated[
    ProjectService,
    Depends(get_project_service),
]


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    _: CurrentUser, project_service: ProjectServiceDependency
) -> list[ProjectResponse]:
    return [ProjectResponse.model_validate(item) for item in await project_service.list()]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def register_project(
    request: ProjectCreate,
    user: CurrentUser,
    db: DbSession,
    project_service: ProjectServiceDependency,
) -> ProjectResponse:
    try:
        project = await project_service.register(request, user.id)
    except GitLabError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await db.commit()
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    _: CurrentUser,
    project_service: ProjectServiceDependency,
) -> ProjectResponse:
    try:
        return ProjectResponse.model_validate(await project_service.get(project_id))
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.put("/{project_id}/token", response_model=ProjectResponse)
async def replace_project_token(
    project_id: uuid.UUID,
    request: ProjectTokenUpdate,
    _: CurrentUser,
    db: DbSession,
    project_service: ProjectServiceDependency,
) -> ProjectResponse:
    try:
        project = await project_service.replace_token(project_id, request.access_token)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return ProjectResponse.model_validate(project)


@router.post("/{project_id}/fetch")
async def fetch_project(
    project_id: uuid.UUID,
    _: CurrentUser,
    project_service: ProjectServiceDependency,
) -> dict[str, str]:
    try:
        return {"commit_sha": await project_service.fetch(project_id)}
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/{project_id}/validate", response_model=ProjectValidationResponse)
async def validate_project(
    project_id: uuid.UUID,
    _: CurrentUser,
    project_service: ProjectServiceDependency,
) -> ProjectValidationResponse:
    try:
        result = await project_service.validate(project_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return ProjectValidationResponse.model_validate(result)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    _: CurrentUser,
    db: DbSession,
    project_service: ProjectServiceDependency,
) -> Response:
    try:
        await project_service.delete(project_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
