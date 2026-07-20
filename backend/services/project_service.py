from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.models import Project, WorkflowRun
from backend.integrations.code_host import code_host_client, git_username, repository_locator
from backend.integrations.git_manager import GitManager, project_git_locks
from backend.schemas.project import ProjectCreate
from backend.services.crypto import SecretCipher


class ProjectService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        cipher: SecretCipher,
        git: GitManager,
    ) -> None:
        self.session = session
        self.settings = settings
        self.cipher = cipher
        self.git = git

    async def list(self) -> list[Project]:
        return list(await self.session.scalars(select(Project).order_by(Project.name)))

    async def get(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise LookupError("Project does not exist")
        return project

    async def register(self, request: ProjectCreate, user_id: uuid.UUID) -> Project:
        token = request.access_token
        async with code_host_client(request.provider, self.settings) as provider:
            metadata = await provider.get_repository(request.provider_project, token)
        if metadata.clone_url and _canonical_git_url(str(request.git_url)) != _canonical_git_url(
            metadata.clone_url
        ):
            raise ValueError("Clone URL does not match the selected provider repository")
        default_branch = metadata.default_branch or request.default_branch
        project_id = uuid.uuid4()
        local_path = self.git.clone_base_path / str(project_id)
        await self.git.clone(
            str(request.git_url),
            local_path,
            token,
            username=git_username(request.provider),
        )
        try:
            project = Project(
                id=project_id,
                name=request.name,
                git_url=str(request.git_url),
                provider=request.provider,
                provider_project_id=metadata.id,
                provider_project_path=metadata.path,
                encrypted_access_token=self.cipher.encrypt(token),
                token_key_version=self.cipher.key_version,
                local_path=str(local_path),
                default_branch=default_branch,
                added_by=user_id,
            )
            self.session.add(project)
            await self.session.flush()
            return project
        except Exception:
            shutil.rmtree(local_path, ignore_errors=True)
            raise

    async def replace_token(self, project_id: uuid.UUID, token: str) -> Project:
        project = await self.get(project_id)
        async with code_host_client(project.provider, self.settings) as provider:
            await provider.get_repository(
                repository_locator(
                    project.provider, project.provider_project_id, project.provider_project_path
                ),
                token,
            )
        project.encrypted_access_token = self.cipher.encrypt(token)
        project.token_key_version = self.cipher.key_version
        await self.session.flush()
        return project

    async def fetch(self, project_id: uuid.UUID) -> str:
        project = await self.get(project_id)
        token = self.cipher.decrypt(project.encrypted_access_token)
        async with project_git_locks.for_project(project.id):
            try:
                await self.git.fetch(
                    Path(project.local_path), token, username=git_username(project.provider)
                )
                return await self.git.resolve_remote_sha(
                    Path(project.local_path), project.default_branch
                )
            finally:
                token = ""

    async def validate(self, project_id: uuid.UUID) -> dict[str, str | bool]:
        project = await self.get(project_id)
        token = self.cipher.decrypt(project.encrypted_access_token)
        try:
            async with code_host_client(project.provider, self.settings) as provider:
                metadata = await provider.get_repository(
                    repository_locator(
                        project.provider,
                        project.provider_project_id,
                        project.provider_project_path,
                    ),
                    token,
                )
            project.provider_project_id = metadata.id
            project.provider_project_path = metadata.path
            return {
                "valid": True,
                "default_branch": metadata.default_branch or project.default_branch,
                "provider_project_path": metadata.path,
            }
        finally:
            token = ""

    async def delete(self, project_id: uuid.UUID) -> None:
        project = await self.get(project_id)
        run_exists = await self.session.scalar(
            select(WorkflowRun.id).where(WorkflowRun.project_id == project.id).limit(1)
        )
        if run_exists:
            raise RuntimeError("Project has workflow run history and cannot be deleted")
        async with project_git_locks.for_project(project.id):
            local_path = self.git.assert_beneath(Path(project.local_path), self.git.clone_base_path)
            changes_path = self.git.assert_beneath(
                self.settings.RUN_DATA_BASE_PATH / "project_changes" / str(project.id),
                self.settings.RUN_DATA_BASE_PATH,
            )
            await self.session.delete(project)
            await self.session.flush()
            shutil.rmtree(local_path, ignore_errors=True)
            shutil.rmtree(changes_path, ignore_errors=True)


def _canonical_git_url(value: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))
