from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from backend.auth.authorization import (
    RUN_TRIGGER,
    WORKFLOW_EDIT,
    WORKFLOW_PUBLISH,
    WORKFLOW_VIEW,
    audit_event,
    authorize_project,
)
from backend.auth.dependencies import CurrentUser, DbSession, require_project_provider
from backend.config import Settings, get_settings
from backend.db.models import Project
from backend.dependencies import Cipher
from backend.engine.validation import direct_references
from backend.integrations.git_manager import GitManager
from backend.lifecycle import runtime
from backend.schemas.run import RunTriggerRequest, RunTriggerResponse
from backend.schemas.workflow import (
    NodeTemplate,
    ValidationIssue,
    WorkflowDefinition,
    WorkflowValidationRequest,
    WorkflowValidationResponse,
)
from backend.services.approval_policy_service import ApprovalPolicyService
from backend.services.workflow_service import WorkflowConflictError, WorkflowService

router = APIRouter(prefix="/projects/{project_id}/workflows", tags=["workflows"])


async def get_workflow_service(
    db: DbSession,
    cipher: Cipher,
    settings: Annotated[Settings, Depends(get_settings)],
) -> WorkflowService:
    return WorkflowService(
        db,
        settings,
        cipher,
        GitManager(
            settings.PROJECT_CLONE_BASE_PATH,
            settings.WORKTREE_BASE_PATH,
            settings.RUN_DATA_BASE_PATH,
        ),
    )


WorkflowServiceDependency = Annotated[WorkflowService, Depends(get_workflow_service)]


async def project_or_404(db: DbSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project does not exist")
    return project


@router.get("")
async def list_workflows(
    project_id: uuid.UUID,
    _: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> dict[str, Any]:
    project = await project_or_404(db, project_id)
    await authorize_project(db, _, project_id, WORKFLOW_VIEW)
    sha, definitions = await workflows.list(project)
    change_status = await workflows.change_status(project)
    return {
        "base_commit_sha": sha,
        **change_status,
        "items": [
            {
                **definition.model_dump(mode="json"),
                "node_count": len(definition.nodes),
            }
            for definition in definitions
        ],
    }


@router.get("/templates")
async def list_node_templates(
    project_id: uuid.UUID,
    _: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> dict[str, Any]:
    project = await project_or_404(db, project_id)
    await authorize_project(db, _, project_id, WORKFLOW_VIEW)
    sha, templates = await workflows.list_templates(project)
    return {
        "base_commit_sha": sha,
        "items": [template.model_dump(mode="json") for template in templates],
        **await workflows.change_status(project),
    }


@router.post("/templates")
async def save_node_template(
    project_id: uuid.UUID,
    request: dict[str, Any],
    user: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> dict[str, Any]:
    project = await project_or_404(db, project_id)
    require_project_provider(user, project.provider)
    await authorize_project(db, user, project_id, WORKFLOW_EDIT)
    raw = request.get("template")
    expected = request.get("expected_base_commit_sha")
    if not isinstance(raw, dict) or not isinstance(expected, str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid template request")
    try:
        template = NodeTemplate.model_validate(raw)
        result = await workflows.save_template(project, template, expected)
        db.add(
            audit_event(
                user,
                "NODE_TEMPLATE_SAVED",
                "node_template",
                project_id=project_id,
                target_id=template.id,
            )
        )
        await db.commit()
        return result
    except WorkflowConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.delete("/templates/{template_id}")
async def delete_node_template(
    project_id: uuid.UUID,
    template_id: str,
    expected_base_commit_sha: str,
    user: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> dict[str, Any]:
    project = await project_or_404(db, project_id)
    require_project_provider(user, project.provider)
    await authorize_project(db, user, project_id, WORKFLOW_EDIT)
    try:
        result = await workflows.delete_template(
            project, template_id, expected_base_commit_sha
        )
        db.add(
            audit_event(
                user,
                "NODE_TEMPLATE_DELETED",
                "node_template",
                project_id=project_id,
                target_id=template_id,
            )
        )
        await db.commit()
        return result
    except WorkflowConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/changes")
async def definition_change_status(
    project_id: uuid.UUID,
    _: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> dict[str, Any]:
    project = await project_or_404(db, project_id)
    await authorize_project(db, _, project_id, WORKFLOW_VIEW)
    return await workflows.change_status(project)


@router.post("/changes/review")
async def publish_definition_changes(
    project_id: uuid.UUID,
    request: dict[str, Any],
    user: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> dict[str, Any]:
    project = await project_or_404(db, project_id)
    require_project_provider(user, project.provider)
    await authorize_project(db, user, project_id, WORKFLOW_PUBLISH)
    expected = request.get("expected_base_commit_sha")
    if not isinstance(expected, str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid review request")
    try:
        _, definitions = await workflows.list(project)
        for definition in definitions:
            await ApprovalPolicyService(db).validate_definition(project, definition)
        result = await workflows.publish_changes(project, user, expected)
        db.add(
            audit_event(
                user,
                "WORKFLOW_CHANGES_PUBLISHED",
                "workflow_change_set",
                project_id=project_id,
                details={"change_request_url": result.get("change_request_url")},
            )
        )
        await db.commit()
        return result
    except WorkflowConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/{workflow_id}")
async def get_workflow(
    project_id: uuid.UUID,
    workflow_id: str,
    _: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> dict[str, Any]:
    project = await project_or_404(db, project_id)
    await authorize_project(db, _, project_id, WORKFLOW_VIEW)
    try:
        sha, definition = await workflows.get(project, workflow_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {
        "base_commit_sha": sha,
        "workflow": definition.model_dump(mode="json"),
        **await workflows.change_status(project),
    }


@router.post("/validate", response_model=WorkflowValidationResponse)
async def validate_workflow(
    project_id: uuid.UUID,
    request: WorkflowValidationRequest,
    _: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> WorkflowValidationResponse:
    project = await project_or_404(db, project_id)
    await authorize_project(db, _, project_id, WORKFLOW_EDIT)
    report = await workflows.validate(project, request.workflow, request.proposed_related_workflows)
    if report.valid:
        try:
            definition = WorkflowDefinition.model_validate(request.workflow)
            await ApprovalPolicyService(db).validate_definition(project, definition)
        except ValueError as exc:
            report.valid = False
            report.errors.append(
                ValidationIssue(path="workflow", code="GOVERNANCE_ERROR", message=str(exc))
            )
    return report


@router.post("/{workflow_id}/runs", response_model=RunTriggerResponse)
async def trigger_workflow(
    project_id: uuid.UUID,
    workflow_id: str,
    request: RunTriggerRequest,
    user: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> RunTriggerResponse:
    project = await project_or_404(db, project_id)
    require_project_provider(user, project.provider)
    await authorize_project(db, user, project_id, RUN_TRIGGER)
    try:
        run = await workflows.create_run(
            project,
            user,
            workflow_id,
            request.base_ref,
            request.inputs,
            use_local_definitions=request.use_local_definitions,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await runtime.schedule(run.id)
    db.add(
        audit_event(
            user,
            "RUN_TRIGGERED",
            "workflow_run",
            project_id=project_id,
            run_id=run.id,
            target_id=str(run.id),
            details={"workflow_id": workflow_id, "base_commit_sha": run.base_commit_sha},
        )
    )
    await db.commit()
    return RunTriggerResponse(run_id=run.id, status=run.status, base_commit_sha=run.base_commit_sha)


@router.put("/{workflow_id}")
async def save_workflow(
    project_id: uuid.UUID,
    workflow_id: str,
    request: dict[str, Any],
    user: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> dict[str, Any]:
    project = await project_or_404(db, project_id)
    require_project_provider(user, project.provider)
    await authorize_project(db, user, project_id, WORKFLOW_EDIT)
    raw = request.get("workflow")
    expected = request.get("expected_base_commit_sha")
    if not isinstance(raw, dict) or not isinstance(expected, str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid save request")
    try:
        definition = WorkflowDefinition.model_validate(raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if definition.id != workflow_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Workflow ID mismatch")
    try:
        await ApprovalPolicyService(db).validate_definition(project, definition)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    report = await workflows.validate(project, raw, {})
    if not report.valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "VALIDATION_ERROR", "errors": [item.model_dump() for item in report.errors]},
        )
    try:
        result = await workflows.save_draft(project, definition, expected)
        db.add(
            audit_event(
                user,
                "WORKFLOW_SAVED",
                "workflow_definition",
                project_id=project_id,
                target_id=workflow_id,
            )
        )
        await db.commit()
        return result
    except WorkflowConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.delete("/{workflow_id}")
async def delete_workflow(
    project_id: uuid.UUID,
    workflow_id: str,
    expected_base_commit_sha: str,
    user: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> dict[str, Any]:
    project = await project_or_404(db, project_id)
    require_project_provider(user, project.provider)
    await authorize_project(db, user, project_id, WORKFLOW_EDIT)
    _, definitions = await workflows.list(project)
    definition = next((item for item in definitions if item.id == workflow_id), None)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow does not exist")
    referenced_by = [
        item.id
        for item in definitions
        if item.id != workflow_id and workflow_id in direct_references(item)
    ]
    if referenced_by:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "WORKFLOW_REFERENCED",
                "message": "Workflow cannot be deleted while it is referenced",
                "referenced_by": referenced_by,
            },
        )
    try:
        result = await workflows.delete_draft(
            project, workflow_id, expected_base_commit_sha
        )
        db.add(
            audit_event(
                user,
                "WORKFLOW_DELETED",
                "workflow_definition",
                project_id=project_id,
                target_id=workflow_id,
            )
        )
        await db.commit()
        return result
    except WorkflowConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/{workflow_id}/references")
async def workflow_references(
    project_id: uuid.UUID,
    workflow_id: str,
    _: CurrentUser,
    db: DbSession,
    workflows: WorkflowServiceDependency,
) -> dict[str, Any]:
    project = await project_or_404(db, project_id)
    await authorize_project(db, _, project_id, WORKFLOW_VIEW)
    _base_sha, definitions = await workflows.list(project)
    direct = next(
        (definition for definition in definitions if definition.id == workflow_id),
        None,
    )
    if direct is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow does not exist")
    reverse = [
        definition.id for definition in definitions if workflow_id in direct_references(definition)
    ]
    return {"direct": direct_references(direct), "referenced_by": reverse}
