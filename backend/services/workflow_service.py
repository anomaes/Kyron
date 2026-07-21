from __future__ import annotations

import asyncio
import builtins
import json
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.authorization import actor_snapshot
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
from backend.schemas.pi import PiSettings
from backend.schemas.workflow import (
    NodeTemplate,
    WorkflowBundle,
    WorkflowDefinition,
    WorkflowValidationResponse,
)
from backend.services.approval_policy_service import ApprovalPolicyService
from backend.services.crypto import SecretCipher

logger = logging.getLogger(__name__)


class WorkflowConflictError(RuntimeError):
    pass


class WorkflowService:
    """Repository definitions plus project-local, reviewable changes.

    Local changes live below RUN_DATA_BASE_PATH rather than in the shared clone's
    working tree. This keeps Git operations isolated and makes an explicit review
    action the only operation that commits or pushes definition files.
    """

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
        sha, definitions, _templates = await self._load_all(project)
        return sha, [definitions[key] for key in sorted(definitions)]

    async def get(self, project: Project, workflow_id: str) -> tuple[str, WorkflowDefinition]:
        sha, definitions, _templates = await self._load_all(project)
        if workflow_id not in definitions:
            raise LookupError("Workflow does not exist")
        return sha, definitions[workflow_id]

    async def list_templates(self, project: Project) -> tuple[str, builtins.list[NodeTemplate]]:
        sha, _definitions, templates = await self._load_all(project)
        return sha, [templates[key] for key in sorted(templates)]

    async def change_status(self, project: Project) -> dict[str, Any]:
        root = self._changes_root(project)
        metadata = await self._read_json(root / "publication.json")
        return {
            "outgoing_changes": await self._entry_count(root / "outgoing"),
            "in_review_changes": await self._entry_count(root / "published"),
            "change_request_url": (
                metadata.get("change_request_url") if isinstance(metadata, dict) else None
            ),
        }

    async def validate(
        self,
        project: Project,
        proposed: dict[str, Any],
        proposed_related: dict[str, dict[str, Any]],
    ) -> WorkflowValidationResponse:
        _, definitions, _templates = await self._load_all(project)
        root, errors = parse_workflow(proposed)
        if root is None:
            logger.warning(
                "Proposed workflow schema parsing failed (project=%s): %s",
                project.id,
                _issue_details(errors),
            )
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
            logger.warning(
                "Related workflow schema parsing failed (project=%s, workflow=%s): %s",
                project.id,
                root.id,
                _issue_details(errors),
            )
            return WorkflowValidationResponse(valid=False, errors=errors)
        report = self._validate_bundle(root.id, definitions)
        if not report.valid:
            logger.warning(
                "Proposed workflow bundle validation failed (project=%s, workflow=%s): %s",
                project.id,
                root.id,
                _issue_details(report.errors),
            )
        return report

    async def save_draft(
        self,
        project: Project,
        workflow: WorkflowDefinition,
        expected_base_commit_sha: str,
    ) -> dict[str, Any]:
        sha, remote, _templates = await self._load_remote(project)
        if sha != expected_base_commit_sha:
            raise WorkflowConflictError("Workflow base branch changed; reload the editor")
        published = dict(remote)
        await self._overlay_workflows(published, self._changes_root(project) / "published")
        path = self._changes_root(project) / "outgoing" / "workflows" / f"{workflow.id}.json"
        marker = self._changes_root(project) / "outgoing" / "deleted_workflows" / workflow.id
        await self._remove_file(marker)
        if published.get(workflow.id) == workflow:
            await self._remove_file(path)
        else:
            await self._write_model(path, workflow)
        return {"saved": True, **await self.change_status(project)}

    async def delete_draft(
        self,
        project: Project,
        workflow_id: str,
        expected_base_commit_sha: str,
    ) -> dict[str, Any]:
        self._require_identifier(workflow_id)
        sha, remote, _templates = await self._load_remote(project)
        if sha != expected_base_commit_sha:
            raise WorkflowConflictError("Workflow base branch changed; reload the catalog")
        root = self._changes_root(project)
        published = dict(remote)
        await self._overlay_workflows(published, root / "published")
        await self._remove_file(root / "outgoing" / "workflows" / f"{workflow_id}.json")
        marker = root / "outgoing" / "deleted_workflows" / workflow_id
        if workflow_id in published:
            await self._write_text(marker, "delete\n")
        else:
            await self._remove_file(marker)
        return {"saved": True, **await self.change_status(project)}

    async def save_template(
        self,
        project: Project,
        template: NodeTemplate,
        expected_base_commit_sha: str,
    ) -> dict[str, Any]:
        sha, _workflows, remote = await self._load_remote(project)
        if sha != expected_base_commit_sha:
            raise WorkflowConflictError("Template base branch changed; reload the editor")
        root = self._changes_root(project)
        published = dict(remote)
        await self._overlay_templates(published, root / "published")
        path = root / "outgoing" / "templates" / f"{template.id}.json"
        marker = root / "outgoing" / "deleted_templates" / template.id
        await self._remove_file(marker)
        if published.get(template.id) == template:
            await self._remove_file(path)
        else:
            await self._write_model(path, template)
        return {
            "saved": True,
            "template": template.model_dump(mode="json"),
            **await self.change_status(project),
        }

    async def delete_template(
        self,
        project: Project,
        template_id: str,
        expected_base_commit_sha: str,
    ) -> dict[str, Any]:
        self._require_identifier(template_id)
        sha, _workflows, remote = await self._load_remote(project)
        if sha != expected_base_commit_sha:
            raise WorkflowConflictError("Template base branch changed; reload the editor")
        root = self._changes_root(project)
        published = dict(remote)
        await self._overlay_templates(published, root / "published")
        await self._remove_file(root / "outgoing" / "templates" / f"{template_id}.json")
        marker = root / "outgoing" / "deleted_templates" / template_id
        if template_id in published:
            await self._write_text(marker, "delete\n")
        else:
            await self._remove_file(marker)
        return {"saved": True, **await self.change_status(project)}

    async def publish_changes(
        self,
        project: Project,
        user: AuthenticatedUser,
        expected_base_commit_sha: str,
    ) -> dict[str, Any]:
        if user.provider != project.provider:
            raise PermissionError("Authentication provider does not match project provider")
        status = await self.change_status(project)
        if not status["outgoing_changes"]:
            raise ValueError("There are no outgoing changes to review")

        token = self.cipher.decrypt(project.encrypted_access_token)
        repository = Path(project.local_path)
        operation_id = uuid.uuid4()
        worktree = self.git.worktree_base_path / f"definition-{operation_id}"
        changes_root = self._changes_root(project)
        metadata = await self._read_json(changes_root / "publication.json")
        existing = metadata if isinstance(metadata, dict) else {}
        branch = str(
            existing.get("branch_name") or f"workflow_definition/review_{operation_id.hex[:8]}"
        )
        try:
            async with project_git_locks.for_project(project.id):
                await self.git.fetch(repository, token, username=git_username(project.provider))
                current_sha = await self.git.resolve_remote_sha(repository, project.default_branch)
                if current_sha != expected_base_commit_sha:
                    raise WorkflowConflictError("Workflow base branch changed; reload the catalog")
                await self.git.run(
                    ["worktree", "add", "-B", branch, str(worktree), current_sha],
                    cwd=repository,
                )
                await self._configure_definition_worktree(worktree)
                await self._apply_layer_to_worktree(worktree, changes_root / "published")
                await self._apply_layer_to_worktree(worktree, changes_root / "outgoing")
                commit_sha = await self.git.checkpoint(
                    worktree, "Update Kyron workflows and node templates"
                )
                if commit_sha == current_sha:
                    raise ValueError("Outgoing definitions match the default branch")
                await self.git.push(
                    worktree,
                    branch,
                    token,
                    username=git_username(project.provider),
                    force_with_lease=bool(existing),
                )
                if existing.get("change_request_url"):
                    result = {
                        "branch_name": branch,
                        "change_request_number": existing.get("change_request_number"),
                        "change_request_url": existing["change_request_url"],
                    }
                else:
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
                            title="Update Kyron workflows and node templates",
                            description=(
                                "Project-local workflow and node-template changes created by Kyron."
                            ),
                            reviewers=[
                                ProviderUser(
                                    id=user.provider_user_id,
                                    username=user.provider_username,
                                )
                            ],
                        )
                    result = {
                        "branch_name": branch,
                        "change_request_number": change_request.number,
                        "change_request_url": change_request.url,
                    }
                await self._merge_outgoing_into_published(changes_root)
                await self._write_json(changes_root / "publication.json", result)
                return {**result, **await self.change_status(project)}
        finally:
            if await asyncio.to_thread(worktree.exists):
                await self.git.remove_worktree(repository, worktree, branch=None)
            token = ""

    async def snapshot_for_run(
        self,
        project: Project,
        workflow_id: str,
        base_ref: str,
        *,
        use_local_definitions: bool = False,
    ) -> tuple[str, WorkflowBundle]:
        logger.info(
            "Creating workflow snapshot (project=%s, workflow=%s, base_ref=%s, local=%s)",
            project.id,
            workflow_id,
            base_ref,
            use_local_definitions,
        )
        token = self.cipher.decrypt(project.encrypted_access_token)
        repository = Path(project.local_path)
        snapshot_worktree: Path | None = None
        try:
            async with project_git_locks.for_project(project.id):
                await self.git.fetch(repository, token, username=git_username(project.provider))
                sha = await self.git.resolve_remote_sha(repository, base_ref)
                if use_local_definitions:
                    operation_id = uuid.uuid4()
                    branch = f"workflow_definition/local_{operation_id.hex[:12]}"
                    snapshot_worktree = self.git.worktree_base_path / f"local-{operation_id}"
                    await self.git.run(
                        ["worktree", "add", "-b", branch, str(snapshot_worktree), sha],
                        cwd=repository,
                    )
                    await self._configure_definition_worktree(snapshot_worktree)
                    changes_root = self._changes_root(project)
                    await self._apply_layer_to_worktree(
                        snapshot_worktree, changes_root / "published"
                    )
                    await self._apply_layer_to_worktree(
                        snapshot_worktree, changes_root / "outgoing"
                    )
                    sha = await self.git.checkpoint(
                        snapshot_worktree, "Snapshot local Kyron definitions for test run"
                    )
                bundle = await WorkflowSnapshotLoader(self.git).load(
                    repository,
                    sha,
                    workflow_id,
                    max_timeout=self.settings.MAX_NODE_TIMEOUT_SECONDS,
                    max_review_iterations=self.settings.MAX_REVIEW_ITERATIONS,
                    max_subworkflow_depth=self.settings.MAX_SUBWORKFLOW_DEPTH,
                    project_pi=PiSettings.model_validate(project.pi),
                )
                logger.info(
                    "Workflow snapshot created (project=%s, workflow=%s, commit=%s)",
                    project.id,
                    workflow_id,
                    sha[:12],
                )
                return sha, bundle
        finally:
            if snapshot_worktree is not None:
                if await asyncio.to_thread(snapshot_worktree.exists):
                    await self.git.remove_worktree(repository, snapshot_worktree, branch=None)
            token = ""

    async def create_run(
        self,
        project: Project,
        user: AuthenticatedUser,
        workflow_id: str,
        base_ref: str,
        inputs: dict[str, Any],
        *,
        use_local_definitions: bool = False,
    ) -> WorkflowRun:
        if user.provider != project.provider:
            raise PermissionError("Authentication provider does not match project provider")
        sha, bundle = await self.snapshot_for_run(
            project,
            workflow_id,
            base_ref,
            use_local_definitions=use_local_definitions,
        )
        workflow = bundle.workflows[workflow_id]
        await ApprovalPolicyService(self.session).validate_bundle(project, bundle)
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
            local_definition_test=use_local_definitions,
            public_context={**workflow.variables, **validated_inputs},
            trigger_actor_snapshot=actor_snapshot(user),
            reviewer_provider=user.provider,
            reviewer_provider_user_id=user.provider_user_id,
            reviewer_provider_username=user.provider_username,
        )
        self.session.add(run)
        await self.session.commit()
        logger.info(
            "Workflow run queued (run=%s, project=%s, workflow=%s, commit=%s, local=%s)",
            run.id,
            project.id,
            workflow_id,
            sha[:12],
            use_local_definitions,
        )
        return run

    def _validate_bundle(
        self, root_id: str, definitions: dict[str, WorkflowDefinition]
    ) -> WorkflowValidationResponse:
        return validate_workflow_bundle(
            root_id,
            definitions,
            filename=f"{root_id}.json",
            max_timeout=self.settings.MAX_NODE_TIMEOUT_SECONDS,
            max_review_iterations=self.settings.MAX_REVIEW_ITERATIONS,
            max_subworkflow_depth=self.settings.MAX_SUBWORKFLOW_DEPTH,
        )

    async def _load_all(
        self, project: Project
    ) -> tuple[str, dict[str, WorkflowDefinition], dict[str, NodeTemplate]]:
        sha, definitions, templates = await self._load_remote(project)
        root = self._changes_root(project)
        await self._reconcile_published(root, definitions, templates)
        await self._overlay_workflows(definitions, root / "published")
        await self._overlay_workflows(definitions, root / "outgoing")
        await self._overlay_templates(templates, root / "published")
        await self._overlay_templates(templates, root / "outgoing")
        return sha, definitions, templates

    async def _load_remote(
        self, project: Project
    ) -> tuple[str, dict[str, WorkflowDefinition], dict[str, NodeTemplate]]:
        token = self.cipher.decrypt(project.encrypted_access_token)
        repository = Path(project.local_path)
        try:
            async with project_git_locks.for_project(project.id):
                await self.git.fetch(repository, token, username=git_username(project.provider))
                sha = await self.git.resolve_remote_sha(repository, project.default_branch)
                files = await self.git.list_files(repository, sha, ".workflowEngine")
                definitions: dict[str, WorkflowDefinition] = {}
                templates: dict[str, NodeTemplate] = {}
                for filename in files:
                    if not filename.endswith(".json"):
                        continue
                    raw = await self.git.show_file(repository, sha, filename)
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "Definition JSON parsing failed "
                            "(project=%s, file=%s, commit=%s, line=%s, column=%s): %s",
                            project.id,
                            filename,
                            sha[:12],
                            exc.lineno,
                            exc.colno,
                            exc.msg,
                        )
                        raise
                    if not isinstance(data, dict):
                        logger.warning(
                            "Definition parsing skipped (project=%s, file=%s, commit=%s): "
                            "top-level JSON value is %s, expected an object",
                            project.id,
                            filename,
                            sha[:12],
                            type(data).__name__,
                        )
                        continue
                    if filename.startswith(".workflowEngine/templates/"):
                        try:
                            template = NodeTemplate.model_validate(data)
                        except ValueError as exc:
                            logger.warning(
                                "Node template parsing skipped "
                                "(project=%s, file=%s, commit=%s): %s",
                                project.id,
                                filename,
                                sha[:12],
                                exc,
                            )
                            continue
                        if filename.endswith(f"/{template.id}.json"):
                            templates[template.id] = template
                        else:
                            logger.warning(
                                "Node template parsing skipped "
                                "(project=%s, file=%s, commit=%s): declared ID %s "
                                "does not match filename",
                                project.id,
                                filename,
                                sha[:12],
                                template.id,
                            )
                        continue
                    if Path(filename).parent != Path(".workflowEngine"):
                        continue
                    definition, errors = parse_workflow(data, filename)
                    if definition is not None and not errors:
                        definitions[definition.id] = definition
                    else:
                        logger.warning(
                            "Workflow schema parsing skipped "
                            "(project=%s, file=%s, commit=%s): %s",
                            project.id,
                            filename,
                            sha[:12],
                            _issue_details(errors),
                        )
                logger.debug(
                    "Repository definitions loaded "
                    "(project=%s, commit=%s, workflows=%s, templates=%s)",
                    project.id,
                    sha[:12],
                    len(definitions),
                    len(templates),
                )
                return sha, definitions, templates
        finally:
            token = ""

    async def _overlay_workflows(
        self, definitions: dict[str, WorkflowDefinition], layer: Path
    ) -> None:
        for marker in await self._files(layer / "deleted_workflows"):
            definitions.pop(marker.name, None)
        for path in await self._files(layer / "workflows", suffix=".json"):
            data = await self._read_json(path)
            if isinstance(data, dict):
                definition, errors = parse_workflow(data, str(path))
                if definition is not None and not errors and path.stem == definition.id:
                    definitions[definition.id] = definition
                elif errors:
                    logger.warning(
                        "Local workflow schema parsing skipped (file=%s): %s",
                        path,
                        _issue_details(errors),
                    )
                elif definition is not None:
                    logger.warning(
                        "Local workflow parsing skipped (file=%s): declared ID %s "
                        "does not match filename",
                        path,
                        definition.id,
                    )
            elif data is not None:
                logger.warning(
                    "Local workflow parsing skipped (file=%s): top-level JSON value is %s, "
                    "expected an object",
                    path,
                    type(data).__name__,
                )

    async def _overlay_templates(self, templates: dict[str, NodeTemplate], layer: Path) -> None:
        for marker in await self._files(layer / "deleted_templates"):
            templates.pop(marker.name, None)
        for path in await self._files(layer / "templates", suffix=".json"):
            data = await self._read_json(path)
            if isinstance(data, dict):
                try:
                    template = NodeTemplate.model_validate(data)
                except ValueError:
                    continue
                if path.stem == template.id:
                    templates[template.id] = template

    async def _apply_layer_to_worktree(self, worktree: Path, layer: Path) -> None:
        definitions = worktree / ".workflowEngine"
        for marker in await self._files(layer / "deleted_workflows"):
            await self._remove_file(definitions / f"{marker.name}.json")
        for marker in await self._files(layer / "deleted_templates"):
            await self._remove_file(definitions / "templates" / f"{marker.name}.json")
        for path in await self._files(layer / "workflows", suffix=".json"):
            await self._copy_file(path, definitions / path.name)
        for path in await self._files(layer / "templates", suffix=".json"):
            await self._copy_file(path, definitions / "templates" / path.name)

    async def _merge_outgoing_into_published(self, root: Path) -> None:
        outgoing = root / "outgoing"
        published = root / "published"
        for path in await self._files(outgoing / "workflows", suffix=".json"):
            await self._remove_file(published / "deleted_workflows" / path.stem)
            await self._copy_file(path, published / "workflows" / path.name)
        for marker in await self._files(outgoing / "deleted_workflows"):
            await self._remove_file(published / "workflows" / f"{marker.name}.json")
            await self._copy_file(marker, published / "deleted_workflows" / marker.name)
        for path in await self._files(outgoing / "templates", suffix=".json"):
            await self._remove_file(published / "deleted_templates" / path.stem)
            await self._copy_file(path, published / "templates" / path.name)
        for marker in await self._files(outgoing / "deleted_templates"):
            await self._remove_file(published / "templates" / f"{marker.name}.json")
            await self._copy_file(marker, published / "deleted_templates" / marker.name)
        if await asyncio.to_thread(outgoing.exists):
            await asyncio.to_thread(shutil.rmtree, outgoing)

    async def _reconcile_published(
        self,
        root: Path,
        remote_workflows: dict[str, WorkflowDefinition],
        remote_templates: dict[str, NodeTemplate],
    ) -> None:
        published = root / "published"
        for path in await self._files(published / "workflows", suffix=".json"):
            data = await self._read_json(path)
            if isinstance(data, dict):
                definition, errors = parse_workflow(data)
                if (
                    definition is not None
                    and not errors
                    and remote_workflows.get(path.stem) == definition
                ):
                    await self._remove_file(path)
        for marker in await self._files(published / "deleted_workflows"):
            if marker.name not in remote_workflows:
                await self._remove_file(marker)
        for path in await self._files(published / "templates", suffix=".json"):
            data = await self._read_json(path)
            if isinstance(data, dict):
                try:
                    template = NodeTemplate.model_validate(data)
                except ValueError:
                    continue
                if remote_templates.get(path.stem) == template:
                    await self._remove_file(path)
        for marker in await self._files(published / "deleted_templates"):
            if marker.name not in remote_templates:
                await self._remove_file(marker)
        if await self._entry_count(published) == 0:
            await self._remove_file(root / "publication.json")

    async def _configure_definition_worktree(self, worktree: Path) -> None:
        await self.git.run(["config", "user.name", "Workflow Engine"], cwd=worktree)
        await self.git.run(["config", "user.email", "workflow-engine@noreply.local"], cwd=worktree)

    def _changes_root(self, project: Project) -> Path:
        root = self.settings.RUN_DATA_BASE_PATH / "project_changes" / str(project.id)
        return self.git.assert_beneath(root, self.settings.RUN_DATA_BASE_PATH)

    @staticmethod
    def _require_identifier(value: str) -> None:
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,254}", value) is None:
            raise ValueError("Definition ID is invalid")

    @staticmethod
    async def _files(directory: Path, *, suffix: str | None = None) -> builtins.list[Path]:
        if not await asyncio.to_thread(directory.is_dir):
            return []
        paths = await asyncio.to_thread(lambda: sorted(directory.iterdir()))
        return [
            path for path in paths if path.is_file() and (suffix is None or path.suffix == suffix)
        ]

    async def _entry_count(self, layer: Path) -> int:
        total = 0
        for directory in (
            "workflows",
            "templates",
            "deleted_workflows",
            "deleted_templates",
        ):
            total += len(await self._files(layer / directory))
        return total

    @staticmethod
    async def _read_json(path: Path) -> Any:
        if not await asyncio.to_thread(path.is_file):
            return None
        try:
            raw = await asyncio.to_thread(path.read_text, "utf-8")
            return json.loads(raw)
        except OSError as exc:
            logger.warning("Could not read local definition JSON (file=%s): %s", path, exc)
            return None
        except json.JSONDecodeError as exc:
            logger.warning(
                "Local definition JSON parsing failed (file=%s, line=%s, column=%s): %s",
                path,
                exc.lineno,
                exc.colno,
                exc.msg,
            )
            return None

    async def _write_model(self, path: Path, model: WorkflowDefinition | NodeTemplate) -> None:
        await self._write_json(path, model.model_dump(mode="json", exclude_none=True))

    async def _write_json(self, path: Path, value: Any) -> None:
        serialized = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        await self._write_text(path, serialized)

    @staticmethod
    async def _write_text(path: Path, value: str) -> None:
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        await asyncio.to_thread(temporary.write_text, value, "utf-8")
        await asyncio.to_thread(temporary.replace, path)

    @staticmethod
    async def _copy_file(source: Path, destination: Path) -> None:
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, source, destination)

    @staticmethod
    async def _remove_file(path: Path) -> None:
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            pass


def _issue_details(issues: list[Any]) -> str:
    return "; ".join(f"{issue.path} [{issue.code}]: {issue.message}" for issue in issues)
