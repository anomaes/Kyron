from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import NodeAttempt, NodeExecution, WorkflowRun
from backend.engine.output_paths import node_attempt_directory
from backend.engine.pi.file_summary import summarize_pi_file
from backend.engine.pi.live_summaries import snapshot
from backend.engine.pi.model_identity import merge_pi_models, normalize_pi_models
from backend.engine.pi.usage import (
    add_pi_usage,
    empty_pi_usage,
    normalize_pi_usage,
)


class PiUsageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._backfilled = False

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
        run_models: list[dict[str, Any]] = []
        breakdown: list[dict[str, Any]] = []
        for node in nodes:
            node_usage = empty_pi_usage()
            node_models: list[dict[str, Any]] = []
            attempt_breakdown: list[dict[str, Any]] = []
            for attempt in attempts_by_node.get(node.id, []):
                usage, models, source = await self._attempt_summary(root, node, attempt)
                add_pi_usage(node_usage, usage)
                merge_pi_models(node_models, models)
                attempt_breakdown.append(
                    {
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "status": attempt.status,
                        "usage": usage,
                        "models": models,
                        "source": source,
                    }
                )
            add_pi_usage(total, node_usage)
            merge_pi_models(run_models, node_models)
            breakdown.append(
                {
                    "node_execution_id": str(node.id),
                    "node_id": node.node_id,
                    "node_path": node.node_path,
                    "status": node.status,
                    "usage": node_usage,
                    "models": node_models,
                    "attempts": attempt_breakdown,
                }
            )
        if self._backfilled:
            await self.session.commit()
        return {
            "usage": total,
            "models": run_models,
            "prompt_node_count": len(nodes),
            "attempt_count": len(attempts),
            "nodes": breakdown,
        }

    async def _attempt_summary(
        self,
        root: Path | None,
        node: NodeExecution,
        attempt: NodeAttempt,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
        stored_usage = normalize_pi_usage(attempt.pi_usage)
        stored_models = normalize_pi_models(attempt.pi_models)
        if attempt.status == "RUNNING":
            live = snapshot(attempt.id)
            if live is not None:
                return live[0], live[1], "live"
            if stored_usage is not None or attempt.pi_models is not None:
                return stored_usage or empty_pi_usage(), stored_models, "persisted"
            return empty_pi_usage(), [], "none"
        if (
            stored_usage is not None
            and attempt.pi_models is not None
            and attempt.status != "RUNNING"
        ):
            return stored_usage, stored_models, "persisted"
        if root is not None:
            output = (
                node_attempt_directory(root, node.node_path, attempt.attempt_number)
                / "pi_events.jsonl"
            ).resolve()
            if output.is_relative_to(root) and await asyncio.to_thread(output.is_file):
                usage, models = await asyncio.to_thread(summarize_pi_file, output)
                selected_models = stored_models if attempt.pi_models is not None else models
                if attempt.pi_usage is None:
                    attempt.pi_usage = usage
                if attempt.pi_models is None:
                    attempt.pi_models = models
                self._backfilled = True
                return stored_usage or usage, selected_models, "events"
        if stored_usage is not None or attempt.pi_models is not None:
            return stored_usage or empty_pi_usage(), stored_models, "persisted"
        return empty_pi_usage(), [], "none"
