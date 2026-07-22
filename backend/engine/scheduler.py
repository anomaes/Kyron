from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backend.schemas.workflow import WorkflowDefinition, WorkflowNode


class LogicalStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


TERMINAL = {LogicalStatus.SUCCESS, LogicalStatus.SKIPPED, LogicalStatus.FAILED}
CONTROL_TYPES = {"subworkflow", "human_feedback", "review_loop"}


@dataclass(slots=True)
class ScheduleDecision:
    nodes: list[WorkflowNode]
    skipped_node_ids: list[str]
    control_boundary: bool


class GraphDeadlockError(RuntimeError):
    pass


class DagScheduler:
    def __init__(self, workflow: WorkflowDefinition) -> None:
        self.workflow = workflow
        self.nodes = {node.id: node for node in workflow.nodes}
        self.incoming = {
            node_id: [edge for edge in workflow.edges if edge.target == node_id]
            for node_id in self.nodes
        }

    def next(
        self,
        statuses: dict[str, LogicalStatus],
        edge_results: dict[str, bool],
    ) -> ScheduleDecision:
        ready: list[WorkflowNode] = []
        skipped: list[str] = []
        for node_id in sorted(self.nodes):
            status = statuses.get(node_id, LogicalStatus.PENDING)
            node = self.nodes[node_id]
            if status == LogicalStatus.RUNNING and node.type in {"subworkflow", "review_loop"}:
                ready.append(node)
                continue
            if status != LogicalStatus.PENDING:
                continue
            incoming = self.incoming[node_id]
            if not incoming:
                ready.append(node)
                continue
            evaluated = [edge for edge in incoming if edge.id in edge_results]
            true_exists = any(edge_results[edge.id] for edge in evaluated)
            predecessors_terminal = all(
                statuses.get(edge.source, LogicalStatus.PENDING) in TERMINAL for edge in incoming
            )
            if node.join == "or":
                if true_exists:
                    ready.append(node)
                elif predecessors_terminal and len(evaluated) == len(incoming):
                    skipped.append(node_id)
            elif predecessors_terminal and len(evaluated) == len(incoming):
                if true_exists:
                    ready.append(node)
                else:
                    skipped.append(node_id)

        process_nodes = sorted(
            (node for node in ready if node.type not in CONTROL_TYPES), key=lambda node: node.id
        )
        if process_nodes:
            return ScheduleDecision(process_nodes, skipped, control_boundary=False)
        control_nodes = sorted(
            (node for node in ready if node.type in CONTROL_TYPES), key=lambda node: node.id
        )
        if control_nodes:
            return ScheduleDecision([control_nodes[0]], skipped, control_boundary=True)
        blocked = [
            node_id
            for node_id in self.nodes
            if statuses.get(node_id, LogicalStatus.PENDING)
            not in {LogicalStatus.SUCCESS, LogicalStatus.SKIPPED}
        ]
        if blocked and not skipped:
            raise GraphDeadlockError(
                f"No nodes are ready while incomplete nodes remain: {', '.join(blocked)}"
            )
        return ScheduleDecision([], skipped, control_boundary=False)

    def complete(self, statuses: dict[str, LogicalStatus]) -> bool:
        return all(
            statuses.get(node_id, LogicalStatus.PENDING)
            in {LogicalStatus.SUCCESS, LogicalStatus.SKIPPED}
            for node_id in self.nodes
        )
