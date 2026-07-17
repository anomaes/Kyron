from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import AuthenticatedUser
from backend.config import Settings
from backend.db.models import Project, WorkflowRun
from backend.engine.snapshot import WorkflowSnapshotLoader
from backend.engine.validation import (
    parse_workflow,
    validate_trigger_inputs,
    validate_workflow_bundle,
)
from backend.integrations.code_host import (
    ProviderUser,
    code_host_client,
    git_username,
    repository_locator,
)
from backend.integrations.git_manager import GitManager, project_git_locks
from backend.schemas.workflow import WorkflowBundle, WorkflowDefinition, WorkflowValidationResponse
from backend.services.crypto import SecretCipher


class WorkflowConflictError(RuntimeError):
    pass


class WorkflowService:
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

    async def list(self, project: Project) -> tuple[str, list[WorkflowDefinition]]:
        sha, definitions = await self._load_all(project)
        return sha, [definitions[key] for key in sorted(definitions)]

    async def get(self, project: Project, workflow_id: str) -> tuple[str, WorkflowDefinition]:
        sha, definitions = await self._load_all(project)
        if workflow_id not in definitions:
            raise LookupError("Workflow does not exist")
        return sha, definitions[workflow_id]

    async def validate(
        self,
        project: Project,
        proposed: dict[str, Any],
        proposed_related: dict[str, dict[str, Any]],
    ) -> WorkflowValidationResponse:
        _, definitions = await self._load_all(project)
        root, errors = parse_workflow(proposed)
        if root is None:
            return WorkflowValidationResponse(valid=False, errors=errors)
        definitions[root.id] = root
        for workflow_id, raw in proposed_related.items():
            definition, related_errors = parse_workflow(
                raw, f"proposed_related_workflows.{workflow_id}"
            )
            errors.extend(related_errors)
            if definition:
                definitions[workflow_id] = definition
        if errors:
            return WorkflowValidationResponse(valid=False, errors=errors)
        return validate_workflow_bundle(
            root.id,
            definitions,
            filename=f"{root.id}.json",
            max_timeout=self.settings.MAX_NODE_TIMEOUT_SECONDS,
            max_review_iterations=self.settings.MAX_REVIEW_ITERATIONS,
            max_subworkflow_depth=self.settings.MAX_SUBWORKFLOW_DEPTH,
        )

    async def snapshot_for_run(
        self, project: Project, workflow_id: str, base_ref: str
    ) -> tuple[str, WorkflowBundle]:
        token = self.cipher.decrypt(project.encrypted_access_token)
        repository = Path(project.local_path)
        try:
            async with project_git_locks.for_project(project.id):
                await self.git.fetch(
                    repository, token, username=git_username(project.provider)
                )
                sha = await self.git.resolve_remote_sha(repository, base_ref)
                bundle = await WorkflowSnapshotLoader(self.git).load(
                    repository,
                    sha,
                    workflow_id,
                    max_timeout=self.settings.MAX_NODE_TIMEOUT_SECONDS,
                    max_review_iterations=self.settings.MAX_REVIEW_ITERATIONS,
                    max_subworkflow_depth=self.settings.MAX_SUBWORKFLOW_DEPTH,
                )
                return sha, bundle
        finally:
            token = ""

    async def create_run(
        self,
        project: Project,
        user: AuthenticatedUser,
        workflow_id: str,
        base_ref: str,
        inputs: dict[str, Any],
    ) -> WorkflowRun:
        if user.provider != project.provider:
            raise PermissionError("Authentication provider does not match project provider")
        sha, bundle = await self.snapshot_for_run(project, workflow_id, base_ref)
        workflow = bundle.workflows[workflow_id]
        validated_inputs = validate_trigger_inputs(workflow, inputs)
        run = WorkflowRun(
            root_workflow_id=workflow_id,
            project_id=project.id,
            triggered_by=user.id,
            status="QUEUED",
            base_ref=base_ref,
            base_commit_sha=sha,
            workflow_definition_commit_sha=sha,
            workflow_bundle_snapshot=bundle.model_dump(mode="json"),
            public_context={**workflow.variables, **validated_inputs},
            reviewer_provider=user.provider,
            reviewer_provider_user_id=user.provider_user_id,
            reviewer_provider_username=user.provider_username,
        )
        self.session.add(run)
        await self.session.commit()
        return run

    async def save_definition(
        self,
        project: Project,
        user: AuthenticatedUser,
        workflow: WorkflowDefinition,
        expected_base_commit_sha: str,
        *,
        delete: bool = False,
    ) -> dict[str, Any]:
        if user.provider != project.provider:
            raise PermissionError("Authentication provider does not match project provider")
        token = self.cipher.decrypt(project.encrypted_access_token)
        repository = Path(project.local_path)
        operation_id = uuid.uuid4()
        branch = f"workflow_definition/{workflow.id}_{operation_id.hex[:8]}"
        worktree = self.git.worktree_base_path / f"definition-{operation_id}"
        try:
            async with project_git_locks.for_project(project.id):
                await self.git.fetch(
                    repository, token, username=git_username(project.provider)
                )
                current_sha = await self.git.resolve_remote_sha(repository, project.default_branch)
                if current_sha != expected_base_commit_sha:
                    raise WorkflowConflictError("Workflow base branch changed; reload the editor")
                await self.git.run(
                    ["worktree", "add", "-b", branch, str(worktree), current_sha],
                    cwd=repository,
                )
                await self.git.run(["config", "user.name", "Workflow Engine"], cwd=worktree)
                await self.git.run(
                    ["config", "user.email", "workflow-engine@noreply.local"],
                    cwd=worktree,
                )
                definition_path = worktree / ".workflowEngine" / f"{workflow.id}.json"
                if delete:
                    await asyncio.to_thread(definition_path.unlink)
                    message = f"Delete workflow: {workflow.name}"
                else:
                    await asyncio.to_thread(
                        definition_path.parent.mkdir, parents=True, exist_ok=True
                    )
                    serialized = (
                        json.dumps(
                            workflow.model_dump(mode="json", exclude_none=True),
                            indent=2,
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    await asyncio.to_thread(definition_path.write_text, serialized, "utf-8")
                    message = f"Update workflow: {workflow.name}"
                await self.git.checkpoint(worktree, message)
                await self.git.push(
                    worktree, branch, token, username=git_username(project.provider)
                )
                async with code_host_client(project.provider, self.settings) as provider:
                    change_request = await provider.create_change_request(
                        repository_locator(
                            project.provider,
                            project.provider_project_id,
                            project.provider_project_path,
                        ),
                        token,
                        source_branch=branch,
                        target_branch=project.default_branch,
                        title=message,
                        description="Workflow definition change created by Kyron.",
                        reviewer=ProviderUser(
                            id=user.provider_user_id, username=user.provider_username
                        ),
                    )
                return {
                    "branch_name": branch,
                    "change_request_number": change_request.number,
                    "change_request_url": change_request.url,
                }
        finally:
            if await asyncio.to_thread(worktree.exists):
                await self.git.remove_worktree(repository, worktree, branch=None)
            token = ""

    async def _load_all(self, project: Project) -> tuple[str, dict[str, WorkflowDefinition]]:
        token = self.cipher.decrypt(project.encrypted_access_token)
        repository = Path(project.local_path)
        try:
            async with project_git_locks.for_project(project.id):
                await self.git.fetch(
                    repository, token, username=git_username(project.provider)
                )
                sha = await self.git.resolve_remote_sha(repository, project.default_branch)
                files = await self.git.list_files(repository, sha, ".workflowEngine")
                definitions: dict[str, WorkflowDefinition] = {}
                for filename in files:
                    if not filename.endswith(".json"):
                        continue
                    raw = await self.git.show_file(repository, sha, filename)
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        continue
                    definition, errors = parse_workflow(data, filename)
                    if definition is None or errors:
                        continue
                    definitions[definition.id] = definition
                return sha, definitions
        finally:
            token = ""
