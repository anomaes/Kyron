from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import ColumnElement, func, select

from backend.approval_policy_defaults import DEFAULT_APPROVAL_POLICY_KEY
from backend.auth.authorization import (
    GATE_OVERRIDE,
    GATE_RESPOND,
    REPORT_VIEW,
    RUN_CONTROL_ANY,
    RUN_CONTROL_OWN,
    RUN_VIEW,
    accessible_project_ids,
    actor_snapshot,
    audit_event,
    authorize_project,
    project_permissions,
)
from backend.auth.dependencies import (
    AuthenticatedUser,
    CurrentUser,
    DbSession,
    websocket_identity,
)
from backend.config import Settings, get_settings
from backend.db.database import session_factory
from backend.db.models import (
    EdgeEvaluation,
    ExecutionWave,
    FeedbackEvent,
    GateDecision,
    GateInstance,
    NodeAttempt,
    NodeExecution,
    ProviderIdentity,
    RunLog,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import RunStatus
from backend.dependencies import Cipher
from backend.engine.cancellation import cancel_run
from backend.engine.process_registry import process_registry
from backend.engine.resume import ResumeError, prepare_resume
from backend.integrations.code_host import create_code_host_client, provider_display_name
from backend.integrations.git_manager import GitManager
from backend.lifecycle import runtime
from backend.schemas.admin import GateOverrideRequest
from backend.schemas.run import FeedbackRequest, PaginatedRuns, RunResponse
from backend.services.feedback_service import FeedbackError, FeedbackService
from backend.services.log_broadcaster import log_broadcaster
from backend.services.report_service import ReportService

router = APIRouter(prefix="/runs", tags=["runs"])
websocket_router = APIRouter(tags=["run logs"])


@router.get("", response_model=PaginatedRuns)
async def list_runs(
    user: CurrentUser,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    project_id: uuid.UUID | None = None,
    root_workflow_id: str | None = None,
    run_status: Annotated[str | None, Query(alias="status")] = None,
    triggered_by: uuid.UUID | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> PaginatedRuns:
    filters: list[ColumnElement[bool]] = []
    allowed_projects = await accessible_project_ids(db, user)
    if allowed_projects is not None:
        if not allowed_projects:
            return PaginatedRuns(items=[], page=page, page_size=page_size, total=0)
        filters.append(WorkflowRun.project_id.in_(allowed_projects))
    if project_id:
        filters.append(WorkflowRun.project_id == project_id)
    if root_workflow_id:
        filters.append(WorkflowRun.root_workflow_id == root_workflow_id)
    if run_status:
        filters.append(WorkflowRun.status == run_status)
    if triggered_by:
        filters.append(WorkflowRun.triggered_by == triggered_by)
    if created_after:
        filters.append(WorkflowRun.created_at >= created_after)
    if created_before:
        filters.append(WorkflowRun.created_at <= created_before)
    total = await db.scalar(select(func.count()).select_from(WorkflowRun).where(*filters))
    runs = list(
        await db.scalars(
            select(WorkflowRun)
            .where(*filters)
            .order_by(WorkflowRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return PaginatedRuns(
        items=[RunResponse.model_validate(run) for run in runs],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RunResponse:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
    await authorize_project(db, user, run.project_id, RUN_VIEW)
    return RunResponse.model_validate(run)


@router.get("/{run_id}/graph")
async def run_graph(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
    await authorize_project(db, user, run.project_id, RUN_VIEW)
    invocations = list(
        await db.scalars(select(WorkflowInvocation).where(WorkflowInvocation.run_id == run_id))
    )
    waves = list(await db.scalars(select(ExecutionWave).where(ExecutionWave.run_id == run_id)))
    nodes = list(await db.scalars(select(NodeExecution).where(NodeExecution.run_id == run_id)))
    attempts = (
        list(
            await db.scalars(
                select(NodeAttempt).where(
                    NodeAttempt.node_execution_id.in_([node.id for node in nodes])
                )
            )
        )
        if nodes
        else []
    )
    edges = list(await db.scalars(select(EdgeEvaluation).where(EdgeEvaluation.run_id == run_id)))
    feedback = list(await db.scalars(select(FeedbackEvent).where(FeedbackEvent.run_id == run_id)))
    gates = list(await db.scalars(select(GateInstance).where(GateInstance.run_id == run_id)))
    decisions = (
        list(
            await db.scalars(
                select(GateDecision).where(
                    GateDecision.gate_instance_id.in_([item.id for item in gates])
                )
            )
        )
        if gates
        else []
    )
    return {
        "snapshot": run.workflow_bundle_snapshot,
        "invocations": [_model(item) for item in invocations],
        "waves": [_model(item) for item in waves],
        "nodes": [_model(item) for item in nodes],
        "attempts": [_model(item) for item in attempts],
        "edge_evaluations": [_model(item) for item in edges],
        "feedback": [_model(item) for item in feedback],
        "gates": [_model(item) for item in gates],
        "gate_decisions": [_model(item) for item in decisions],
    }


@router.get("/{run_id}/report")
async def run_report(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
    await authorize_project(db, user, run.project_id, REPORT_VIEW)
    return await ReportService(db).get(run)


@router.get("/{run_id}/logs")
async def run_logs(
    run_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    after_id: int = 0,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
) -> list[dict[str, Any]]:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
    await authorize_project(db, user, run.project_id, RUN_VIEW)
    logs = list(
        await db.scalars(
            select(RunLog)
            .where(RunLog.run_id == run_id, RunLog.id > after_id)
            .order_by(RunLog.id)
            .limit(limit)
        )
    )
    return [_log_event(log) for log in logs]


@router.get("/{run_id}/nodes/{node_execution_id}")
async def node_detail(
    run_id: uuid.UUID,
    node_execution_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
    await authorize_project(db, user, run.project_id, RUN_VIEW)
    node = await db.scalar(
        select(NodeExecution).where(
            NodeExecution.id == node_execution_id, NodeExecution.run_id == run_id
        )
    )
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node execution does not exist")
    attempts = list(
        await db.scalars(
            select(NodeAttempt)
            .where(NodeAttempt.node_execution_id == node.id)
            .order_by(NodeAttempt.attempt_number)
        )
    )
    return {"node": _model(node), "attempts": [_model(item) for item in attempts]}


@router.get("/{run_id}/nodes/{node_execution_id}/output")
async def node_output(
    run_id: uuid.UUID,
    node_execution_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    stream: str = "stdout",
    attempt: int | None = None,
    tail_lines: Annotated[int | None, Query(ge=1, le=10000)] = None,
) -> Response:
    if stream not in {"stdout", "stderr", "pi_events"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown output stream")
    run = await db.get(WorkflowRun, run_id)
    node = await db.scalar(
        select(NodeExecution).where(
            NodeExecution.id == node_execution_id, NodeExecution.run_id == run_id
        )
    )
    if run is None or node is None or not run.run_data_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Output does not exist")
    await authorize_project(db, user, run.project_id, RUN_VIEW)
    selected_attempt = attempt or node.current_attempt
    if selected_attempt < 1:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Output does not exist")
    current_relative = node.stdout_path if stream != "stderr" else node.stderr_path
    if not current_relative:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Output does not exist")
    current_path = Path(current_relative)
    filename = {
        "stdout": "stdout.log",
        "stderr": "stderr.log",
        "pi_events": "pi_events.jsonl",
    }[stream]
    relative = current_path.parent.parent / f"attempt-{selected_attempt}" / filename
    root = await asyncio.to_thread(Path(run.run_data_path).resolve)
    output = await asyncio.to_thread((root / relative).resolve)
    if not output.is_relative_to(root) or not await asyncio.to_thread(output.is_file):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Output does not exist")
    content = await asyncio.to_thread(output.read_text, "utf-8", "replace")
    if tail_lines:
        content = "\n".join(content.splitlines()[-tail_lines:])
    return Response(content, media_type="text/plain; charset=utf-8")


@router.post("/{run_id}/cancel", response_model=RunResponse)
async def cancel(
    run_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RunResponse:
    try:
        existing = await db.get(WorkflowRun, run_id)
        if existing is not None:
            await _authorize_control(db, user, existing)
        if existing is not None and existing.reviewer_provider != user.provider:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Sign in with "
                f"{provider_display_name(existing.reviewer_provider)} to control this run",
            )
        run = await cancel_run(
            db,
            runtime.tasks,
            process_registry,
            run_id,
            settings.PROCESS_TERMINATION_GRACE_SECONDS,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.add(
        audit_event(
            user,
            "RUN_CANCELLED",
            "workflow_run",
            project_id=run.project_id,
            run_id=run.id,
            target_id=str(run.id),
        )
    )
    await db.commit()
    if run.status == RunStatus.CANCELLED:
        await ReportService(db).get(run)
    return RunResponse.model_validate(run)


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume(
    run_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RunResponse:
    git = GitManager(
        settings.PROJECT_CLONE_BASE_PATH,
        settings.WORKTREE_BASE_PATH,
        settings.RUN_DATA_BASE_PATH,
    )
    try:
        existing = await db.get(WorkflowRun, run_id)
        if existing is not None:
            await _authorize_control(db, user, existing)
        if existing is not None and existing.reviewer_provider != user.provider:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Sign in with "
                f"{provider_display_name(existing.reviewer_provider)} to control this run",
            )
        run = await prepare_resume(db, git, run_id)
    except ResumeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if run.status in {RunStatus.QUEUED, RunStatus.RESUMING}:
        await runtime.reschedule(run.id)
    db.add(
        audit_event(
            user,
            "RUN_RESUMED",
            "workflow_run",
            project_id=run.project_id,
            run_id=run.id,
            target_id=str(run.id),
        )
    )
    await db.commit()
    return RunResponse.model_validate(run)


async def feedback_service(
    run_id: uuid.UUID,
    db: DbSession,
    cipher: Cipher,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[FeedbackService]:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
    code_host = create_code_host_client(run.reviewer_provider, settings)
    try:
        yield FeedbackService(db, cipher, code_host, runtime.schedule)
    finally:
        await code_host.close()


FeedbackDependency = Annotated[FeedbackService, Depends(feedback_service)]


@router.post("/{run_id}/approve")
async def approve(
    run_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    feedback: FeedbackDependency,
) -> dict[str, Any]:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
    await _authorize_gate_response(db, user, run)
    try:
        event = await feedback.accept(
            run_id,
            event_type="approval",
            source="frontend",
            author_provider=user.provider,
            author_user_id=user.id,
            author_provider_user_id=user.provider_user_id,
            author_username=user.display_name,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except FeedbackError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _model(event)


@router.post("/{run_id}/feedback")
async def submit_feedback(
    run_id: uuid.UUID,
    request: FeedbackRequest,
    user: CurrentUser,
    db: DbSession,
    feedback: FeedbackDependency,
) -> dict[str, Any]:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
    await _authorize_gate_response(db, user, run)
    try:
        event = await feedback.accept(
            run_id,
            event_type="comment",
            source="frontend",
            author_provider=user.provider,
            author_user_id=user.id,
            author_provider_user_id=user.provider_user_id,
            author_username=user.display_name,
            message=request.message,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except FeedbackError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _model(event)


@router.post("/{run_id}/override-gate")
async def override_gate(
    run_id: uuid.UUID,
    request: GateOverrideRequest,
    user: CurrentUser,
    db: DbSession,
    feedback: FeedbackDependency,
) -> dict[str, Any]:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
    await authorize_project(db, user, run.project_id, GATE_OVERRIDE)
    try:
        event = await feedback.override(
            run_id,
            reason=request.reason,
            actor_user_id=user.id,
            actor_snapshot=actor_snapshot(user),
        )
    except FeedbackError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _model(event)


async def websocket_logs(websocket: WebSocket, run_id: uuid.UUID, after_id: int = 0) -> None:
    try:
        _, provider, provider_user_id, _ = websocket_identity(websocket)
    except HTTPException:
        await websocket.close(code=4401)
        return
    async with session_factory() as session:
        identity = await session.scalar(
            select(ProviderIdentity).where(
                ProviderIdentity.provider == provider,
                ProviderIdentity.provider_user_id == provider_user_id,
            )
        )
        run = await session.get(WorkflowRun, run_id)
        if identity is None or run is None:
            await websocket.close(code=4401 if identity is None else 4404)
            return
        user_row = await session.get(User, identity.user_id)
        if user_row is None or not user_row.is_active:
            await websocket.close(code=4403)
            return
        auth_user = AuthenticatedUser(
            id=user_row.id,
            email=user_row.email,
            display_name=user_row.display_name,
            avatar_url=user_row.avatar_url,
            provider=identity.provider,
            provider_user_id=identity.provider_user_id,
            provider_username=identity.username,
            is_system_admin=user_row.is_system_admin,
        )
        if RUN_VIEW not in await project_permissions(session, auth_user, run.project_id):
            await websocket.close(code=4403)
            return
        subscription = log_broadcaster.subscribe(run_id)
        await websocket.accept()
        historical = list(
            await session.scalars(
                select(RunLog)
                .where(RunLog.run_id == run_id, RunLog.id > after_id)
                .order_by(RunLog.id)
            )
        )
        last_sequence = after_id
        for log in historical:
            await websocket.send_json(_log_event(log))
            last_sequence = log.id
        try:
            while True:
                try:
                    event = await asyncio.wait_for(subscription.queue.get(), timeout=20)
                except TimeoutError:
                    await websocket.send_json({"type": "heartbeat"})
                    continue
                if event.get("type") == "log" and int(event.get("sequence", 0)) <= last_sequence:
                    continue
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            log_broadcaster.unsubscribe(subscription)


websocket_router.add_api_websocket_route("/ws/runs/{run_id}/logs", websocket_logs)


def _model(value: Any) -> dict[str, Any]:
    return {column.name: getattr(value, column.key) for column in value.__table__.columns}


def _log_event(log: RunLog) -> dict[str, Any]:
    return {
        "type": "log",
        "sequence": log.id,
        "run_id": str(log.run_id),
        "invocation_path": log.invocation_path,
        "node_path": log.node_path,
        "timestamp": log.timestamp.isoformat(),
        "level": log.level,
        "event_type": log.event_type,
        "message": log.message,
        "metadata": log.log_metadata,
    }


async def _authorize_control(db: DbSession, user: CurrentUser, run: WorkflowRun) -> None:
    permissions = await project_permissions(db, user, run.project_id)
    if RUN_CONTROL_ANY in permissions:
        return
    if RUN_CONTROL_OWN in permissions and run.triggered_by == user.id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "You may only control runs you triggered")


async def _authorize_gate_response(
    db: DbSession, user: CurrentUser, run: WorkflowRun
) -> None:
    permissions = await project_permissions(db, user, run.project_id)
    if GATE_RESPOND in permissions:
        return
    if run.triggered_by == user.id and run.current_node_execution_id is not None:
        default_gate = await db.scalar(
            select(GateInstance.id).where(
                GateInstance.run_id == run.id,
                GateInstance.node_execution_id == run.current_node_execution_id,
                GateInstance.policy_key == DEFAULT_APPROVAL_POLICY_KEY,
                GateInstance.status == "OPEN",
            )
        )
        if default_gate is not None:
            return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "You do not have permission for this project action"
    )
