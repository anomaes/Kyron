from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    AuthorizationAuditEvent,
    ChangeRequestLifecycleEvent,
    GateDecision,
    GateInstance,
    NodeExecution,
    Project,
    RunReport,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import TERMINAL_RUN_STATUSES


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, run: WorkflowRun) -> dict[str, Any]:
        stored = await self.session.scalar(select(RunReport).where(RunReport.run_id == run.id))
        if stored is None:
            payload = await self._build(run)
            if run.status in TERMINAL_RUN_STATUSES:
                stored = RunReport(run_id=run.id, payload=payload)
                self.session.add(stored)
                await self.session.commit()
        else:
            payload = stored.payload
        lifecycle = list(
            await self.session.scalars(
                select(ChangeRequestLifecycleEvent)
                .where(ChangeRequestLifecycleEvent.run_id == run.id)
                .order_by(ChangeRequestLifecycleEvent.created_at)
            )
        )
        return {
            **payload,
            "frozen": stored is not None,
            "generated_at": _json(stored.generated_at) if stored else datetime.now().isoformat(),
            "post_run_lifecycle": [_row(item) for item in lifecycle],
        }

    async def _build(self, run: WorkflowRun) -> dict[str, Any]:
        project = await self.session.get(Project, run.project_id)
        invocations = list(
            await self.session.scalars(
                select(WorkflowInvocation)
                .where(WorkflowInvocation.run_id == run.id)
                .order_by(WorkflowInvocation.started_at, WorkflowInvocation.invocation_path)
            )
        )
        nodes = {
            node.id: node
            for node in await self.session.scalars(
                select(NodeExecution).where(NodeExecution.run_id == run.id)
            )
        }
        invocation_by_id = {item.id: item for item in invocations}
        gates = list(
            await self.session.scalars(
                select(GateInstance)
                .where(GateInstance.run_id == run.id)
                .order_by(GateInstance.opened_at)
            )
        )
        gate_items: list[dict[str, Any]] = []
        for gate in gates:
            decisions = list(
                await self.session.scalars(
                    select(GateDecision)
                    .where(GateDecision.gate_instance_id == gate.id)
                    .order_by(GateDecision.created_at)
                )
            )
            node = nodes.get(gate.node_execution_id)
            invocation = invocation_by_id.get(gate.invocation_id)
            gate_items.append(
                {
                    **_row(gate),
                    "node_id": node.node_id if node else None,
                    "node_path": node.node_path if node else None,
                    "workflow_id": invocation.workflow_id if invocation else None,
                    "invocation_path": invocation.invocation_path if invocation else None,
                    "decisions": [_row(item) for item in decisions],
                }
            )
        audit = list(
            await self.session.scalars(
                select(AuthorizationAuditEvent)
                .where(AuthorizationAuditEvent.run_id == run.id)
                .order_by(AuthorizationAuditEvent.id)
            )
        )
        return {
            "schema_version": 1,
            "run": {
                "id": str(run.id),
                "status": run.status,
                "root_workflow_id": run.root_workflow_id,
                "project_id": str(run.project_id),
                "project_name": project.name if project else "Unknown project",
                "base_ref": run.base_ref,
                "base_commit_sha": run.base_commit_sha,
                "workflow_definition_commit_sha": run.workflow_definition_commit_sha,
                "final_commit_sha": run.final_commit_sha,
                "branch_name": run.branch_name,
                "change_request_url": run.change_request_url,
                "triggered_by": run.trigger_actor_snapshot,
                "created_at": _json(run.created_at),
                "started_at": _json(run.started_at),
                "finished_at": _json(run.finished_at),
                "error_type": run.error_type,
                "error_message": run.error_message,
            },
            "invocations": [_row(item) for item in invocations],
            "gates": gate_items,
            "audit_events": [_row(item) for item in audit],
        }


def _row(value: Any) -> dict[str, Any]:
    return {column.name: _json(getattr(value, column.key)) for column in value.__table__.columns}


def _json(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value
