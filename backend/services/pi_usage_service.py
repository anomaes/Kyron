from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import NodeAttempt, NodeExecution, WorkflowRun
from backend.engine.output_paths import node_attempt_directory
from backend.engine.pi.usage import (
    add_pi_usage,
    aggregate_pi_usage_content,
    empty_pi_usage,
    normalize_pi_usage,
)


class PiUsageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_run_usage(self, run: WorkflowRun) -> dict[str, Any]:
        nodes = list(
            await self.session.scalars(
                select(NodeExecution)
                .where(
                    NodeExecution.run_id == run.id,
                    NodeExecution.node_type == "prompt",
                )
                .order_by(NodeExecution.node_path)
            )
        )
        attempts = (
            list(
                await self.session.scalars(
                    select(NodeAttempt)
                    .where(NodeAttempt.node_execution_id.in_([node.id for node in nodes]))
                    .order_by(NodeAttempt.attempt_number)
                )
            )
            if nodes
            else []
        )
        attempts_by_node: dict[object, list[NodeAttempt]] = {}
        for attempt in attempts:
            attempts_by_node.setdefault(attempt.node_execution_id, []).append(attempt)

        root = (
            await asyncio.to_thread(Path(run.run_data_path).resolve)
            if run.run_data_path
            else None
        )
        total = empty_pi_usage()
        breakdown: list[dict[str, Any]] = []
        for node in nodes:
            node_usage = empty_pi_usage()
            attempt_breakdown: list[dict[str, Any]] = []
            for attempt in attempts_by_node.get(node.id, []):
                usage, source = await self._attempt_usage(root, node, attempt)
                add_pi_usage(node_usage, usage)
                attempt_breakdown.append(
                    {
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "status": attempt.status,
                        "usage": usage,
                        "source": source,
                    }
                )
            add_pi_usage(total, node_usage)
            breakdown.append(
                {
                    "node_execution_id": str(node.id),
                    "node_id": node.node_id,
                    "node_path": node.node_path,
                    "status": node.status,
                    "usage": node_usage,
                    "attempts": attempt_breakdown,
                }
            )
        return {
            "usage": total,
            "prompt_node_count": len(nodes),
            "attempt_count": len(attempts),
            "nodes": breakdown,
        }

    async def _attempt_usage(
        self,
        root: Path | None,
        node: NodeExecution,
        attempt: NodeAttempt,
    ) -> tuple[dict[str, Any], str]:
        stored = normalize_pi_usage(attempt.pi_usage)
        if stored is not None and attempt.status != "RUNNING":
            return stored, "persisted"
        if root is not None:
            output = (
                node_attempt_directory(root, node.node_path, attempt.attempt_number)
                / "pi_events.jsonl"
            ).resolve()
            if output.is_relative_to(root) and await asyncio.to_thread(output.is_file):
                content = await asyncio.to_thread(output.read_text, "utf-8", "replace")
                return aggregate_pi_usage_content(content), "events"
        if stored is not None:
            return stored, "persisted"
        return empty_pi_usage(), "none"
