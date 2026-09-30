from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import NodeAttempt, NodeExecution, WorkflowRun
from backend.engine.output_paths import node_attempt_directory
from backend.engine.pi.file_summary import summarize_pi_file


async def persist_terminal_pi_summaries(
    session: AsyncSession, run_ids: list[uuid.UUID], statuses: tuple[str, ...]
) -> None:
    rows = await session.execute(
        select(NodeAttempt, NodeExecution, WorkflowRun)
        .join(NodeExecution, NodeAttempt.node_execution_id == NodeExecution.id)
        .join(WorkflowRun, NodeExecution.run_id == WorkflowRun.id)
        .where(
            WorkflowRun.id.in_(run_ids),
            NodeExecution.node_type == "prompt",
            NodeAttempt.status.in_(statuses),
        )
    )
    for attempt, node, run in rows:
        if (
            attempt.pi_usage is not None and attempt.pi_models is not None
        ) or not run.run_data_path:
            continue
        root = await asyncio.to_thread(Path(run.run_data_path).resolve)
        output = await asyncio.to_thread(
            (node_attempt_directory(root, node.node_path, attempt.attempt_number)
             / "pi_events.jsonl").resolve
        )
        if not output.is_relative_to(root) or not await asyncio.to_thread(output.is_file):
            continue
        usage, models = await asyncio.to_thread(summarize_pi_file, output)
        if attempt.pi_usage is None:
            attempt.pi_usage = usage
        if attempt.pi_models is None:
            attempt.pi_models = models
