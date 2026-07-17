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
from sqlalchemy import func, select

from backend.auth.dependencies import CurrentUser, DbSession, websocket_identity
from backend.config import Settings, get_settings
from backend.db.database import session_factory
from backend.db.models import (
    EdgeEvaluation,
    ExecutionWave,
    FeedbackEvent,
    NodeAttempt,
    NodeExecution,
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
from backend.integrations.git_manager import GitManager
from backend.integrations.gitlab_client import GitLabClient
from backend.lifecycle import runtime
from backend.schemas.run import FeedbackRequest, PaginatedRuns, RunResponse
from backend.services.cleanup_service import CleanupService
from backend.services.feedback_service import FeedbackError, FeedbackService
from backend.services.log_broadcaster import log_broadcaster

router = APIRouter(prefix="/runs", tags=["runs"])
websocket_router = APIRouter(tags=["run logs"])


@router.get("", response_model=PaginatedRuns)
async def list_runs(
    _: CurrentUser,
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
    filters = []
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
async def get_run(run_id: uuid.UUID, _: CurrentUser, db: DbSession) -> RunResponse:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
    return RunResponse.model_validate(run)


@router.get("/{run_id}/graph")
async def run_graph(run_id: uuid.UUID, _: CurrentUser, db: DbSession) -> dict[str, Any]:
    run = await db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run does not exist")
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
    return {
        "snapshot": run.workflow_bundle_snapshot,
        "invocations": [_model(item) for item in invocations],
        "waves": [_model(item) for item in waves],
        "nodes": [_model(item) for item in nodes],
        "attempts": [_model(item) for item in attempts],
        "edge_evaluations": [_model(item) for item in edges],
        "feedback": [_model(item) for item in feedback],
    }


@router.get("/{run_id}/logs")
async def run_logs(
    run_id: uuid.UUID,
    _: CurrentUser,
    db: DbSession,
    after_id: int = 0,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
) -> list[dict[str, Any]]:
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
    _: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
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
    _: CurrentUser,
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
    _: CurrentUser,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RunResponse:
    try:
        run = await cancel_run(
            db,
            runtime.tasks,
            process_registry,
            run_id,
            settings.PROCESS_TERMINATION_GRACE_SECONDS,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if run.status == RunStatus.CANCELLED and run.mr_iid is None:
        await CleanupService(
            db,
            GitManager(
                settings.PROJECT_CLONE_BASE_PATH,
                settings.WORKTREE_BASE_PATH,
                settings.RUN_DATA_BASE_PATH,
            ),
            process_registry,
            runtime.tasks,
            settings.PROCESS_TERMINATION_GRACE_SECONDS,
        ).cleanup_run(run.id, remove_output=True)
    return RunResponse.model_validate(run)


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume(
    run_id: uuid.UUID,
    _: CurrentUser,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RunResponse:
    git = GitManager(
        settings.PROJECT_CLONE_BASE_PATH,
        settings.WORKTREE_BASE_PATH,
        settings.RUN_DATA_BASE_PATH,
    )
    try:
        run = await prepare_resume(db, git, run_id)
    except ResumeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await runtime.schedule(run.id)
    return RunResponse.model_validate(run)


async def feedback_service(
    db: DbSession,
    cipher: Cipher,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[FeedbackService]:
    gitlab = GitLabClient(str(settings.GITLAB_URL))
    try:
        yield FeedbackService(db, cipher, gitlab, runtime.schedule)
    finally:
        await gitlab.close()


FeedbackDependency = Annotated[FeedbackService, Depends(feedback_service)]


@router.post("/{run_id}/approve")
async def approve(
    run_id: uuid.UUID,
    user: CurrentUser,
    feedback: FeedbackDependency,
) -> dict[str, Any]:
    try:
        event = await feedback.accept(
            run_id,
            event_type="approval",
            source="frontend",
            author_user_id=user.id,
            author_gitlab_user_id=user.gitlab_user_id,
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
    feedback: FeedbackDependency,
) -> dict[str, Any]:
    try:
        event = await feedback.accept(
            run_id,
            event_type="comment",
            source="frontend",
            author_user_id=user.id,
            author_gitlab_user_id=user.gitlab_user_id,
            author_username=user.display_name,
            message=request.message,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except FeedbackError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _model(event)


async def websocket_logs(websocket: WebSocket, run_id: uuid.UUID, after_id: int = 0) -> None:
    try:
        _, gitlab_user_id, _ = websocket_identity(websocket)
    except HTTPException:
        await websocket.close(code=4401)
        return
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.gitlab_user_id == gitlab_user_id))
        run = await session.get(WorkflowRun, run_id)
        if user is None or run is None:
            await websocket.close(code=4401 if user is None else 4404)
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
