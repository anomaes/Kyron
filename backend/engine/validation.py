from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from pydantic import ValidationError

from backend.schemas.workflow import (
    HumanFeedbackNode,
    ReviewLoopNode,
    SubworkflowNode,
    ValidationIssue,
    WorkflowDefinition,
    WorkflowValidationResponse,
)


def parse_workflow(
    data: dict[str, Any], path_prefix: str = "workflow"
) -> tuple[WorkflowDefinition | None, list[ValidationIssue]]:
    try:
        return WorkflowDefinition.model_validate(data), []
    except ValidationError as exc:
        issues = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(item) for item in error["loc"])
            issues.append(
                ValidationIssue(
                    path=f"{path_prefix}.{location}".rstrip("."),
                    code="SCHEMA_ERROR",
                    message=str(error["msg"]),
                )
            )
        return None, issues


def direct_references(workflow: WorkflowDefinition) -> list[str]:
    references: list[str] = []
    for node in workflow.nodes:
        if isinstance(node, SubworkflowNode):
            references.append(node.config.workflow_id)
        elif isinstance(node, ReviewLoopNode):
            references.append(node.config.initial_workflow_id)
            if node.config.revision_workflow_id:
                references.append(node.config.revision_workflow_id)
    return list(dict.fromkeys(references))


def validate_workflow_bundle(
    root_workflow_id: str,
    workflows: dict[str, WorkflowDefinition],
    *,
    filename: str | None = None,
    max_timeout: int = 14400,
    max_review_iterations: int = 10,
    max_subworkflow_depth: int = 8,
) -> WorkflowValidationResponse:
    errors: list[ValidationIssue] = []
    root = workflows.get(root_workflow_id)
    if root is None:
        return WorkflowValidationResponse(
            valid=False,
            errors=[
                ValidationIssue(
                    path="workflow.id",
                    code="MISSING_ROOT_WORKFLOW",
                    message=f"Workflow '{root_workflow_id}' is not available",
                )
            ],
        )
    if filename and filename != f"{root.id}.json":
        errors.append(
            ValidationIssue(
                path="workflow.id",
                code="FILENAME_MISMATCH",
                message=f"Workflow filename must be '{root.id}.json'",
            )
        )

    for workflow_id, workflow in workflows.items():
        errors.extend(_validate_dag(workflow_id, workflow))
        errors.extend(_validate_limits(workflow_id, workflow, max_timeout, max_review_iterations))

    graph = {
        workflow_id: direct_references(workflow) for workflow_id, workflow in workflows.items()
    }
    errors.extend(_validate_references(workflows, graph, max_subworkflow_depth))
    return WorkflowValidationResponse(valid=not errors, errors=errors)


def _validate_dag(workflow_id: str, workflow: WorkflowDefinition) -> list[ValidationIssue]:
    errors: list[ValidationIssue] = []
    prefix = f"workflows.{workflow_id}"
    node_ids = [node.id for node in workflow.nodes]
    node_set = set(node_ids)
    if len(node_set) != len(node_ids):
        errors.append(
            ValidationIssue(
                path=f"{prefix}.nodes", code="DUPLICATE_NODE_ID", message="Node IDs must be unique"
            )
        )
    edge_ids = [edge.id for edge in workflow.edges]
    if len(set(edge_ids)) != len(edge_ids):
        errors.append(
            ValidationIssue(
                path=f"{prefix}.edges", code="DUPLICATE_EDGE_ID", message="Edge IDs must be unique"
            )
        )
    if not node_ids:
        errors.append(
            ValidationIssue(
                path=f"{prefix}.nodes",
                code="NO_START_NODE",
                message="Workflow must contain a start node",
            )
        )
        return errors

    adjacency: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, int] = {node_id: 0 for node_id in node_set}
    for index, edge in enumerate(workflow.edges):
        if edge.source not in node_set:
            errors.append(
                ValidationIssue(
                    path=f"{prefix}.edges[{index}].source",
                    code="MISSING_NODE_REFERENCE",
                    message=f"Source node '{edge.source}' does not exist",
                )
            )
            continue
        if edge.target not in node_set:
            errors.append(
                ValidationIssue(
                    path=f"{prefix}.edges[{index}].target",
                    code="MISSING_NODE_REFERENCE",
                    message=f"Target node '{edge.target}' does not exist",
                )
            )
            continue
        adjacency[edge.source].append(edge.target)
        incoming[edge.target] += 1

    if len(node_set) > 1:
        for node_id in sorted(node_set):
            if incoming[node_id] == 0 and not adjacency[node_id]:
                errors.append(
                    ValidationIssue(
                        path=f"{prefix}.nodes.{node_id}",
                        code="ORPHANED_NODE",
                        message=f"Node '{node_id}' is disconnected",
                    )
                )

    starts = sorted(node_id for node_id, count in incoming.items() if count == 0)
    if not starts:
        errors.append(
            ValidationIssue(
                path=f"{prefix}.nodes",
                code="NO_START_NODE",
                message="Workflow must contain a start node",
            )
        )
    reachable: set[str] = set()
    queue = deque(starts)
    while queue:
        node_id = queue.popleft()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        queue.extend(adjacency[node_id])
    for node_id in sorted(node_set - reachable):
        errors.append(
            ValidationIssue(
                path=f"{prefix}.nodes.{node_id}",
                code="UNREACHABLE_NODE",
                message=f"Node '{node_id}' is not reachable from a start node",
            )
        )

    remaining = dict(incoming)
    queue = deque(starts)
    visited = 0
    while queue:
        source = queue.popleft()
        visited += 1
        for target in adjacency[source]:
            remaining[target] -= 1
            if remaining[target] == 0:
                queue.append(target)
    if visited != len(node_set):
        errors.append(
            ValidationIssue(
                path=f"{prefix}.edges", code="GRAPH_CYCLE", message="Workflow graph must be acyclic"
            )
        )
    return errors


def _validate_limits(
    workflow_id: str,
    workflow: WorkflowDefinition,
    max_timeout: int,
    max_review_iterations: int,
) -> list[ValidationIssue]:
    errors: list[ValidationIssue] = []
    if workflow.settings.timeout_per_node_seconds > max_timeout:
        errors.append(
            ValidationIssue(
                path=f"workflows.{workflow_id}.settings.timeout_per_node_seconds",
                code="LIMIT_EXCEEDED",
                message=f"Default timeout exceeds {max_timeout} seconds",
            )
        )
    if workflow.settings.max_review_iterations > max_review_iterations:
        errors.append(
            ValidationIssue(
                path=f"workflows.{workflow_id}.settings.max_review_iterations",
                code="LIMIT_EXCEEDED",
                message=f"Review iteration limit exceeds {max_review_iterations}",
            )
        )
    for index, node in enumerate(workflow.nodes):
        timeout = getattr(node.config, "timeout", None)
        if timeout is not None and timeout > max_timeout:
            errors.append(
                ValidationIssue(
                    path=f"workflows.{workflow_id}.nodes[{index}].config.timeout",
                    code="LIMIT_EXCEEDED",
                    message=f"Node timeout exceeds {max_timeout} seconds",
                )
            )
        if isinstance(node, ReviewLoopNode):
            iterations = node.config.max_iterations or workflow.settings.max_review_iterations
            if iterations > max_review_iterations:
                errors.append(
                    ValidationIssue(
                        path=f"workflows.{workflow_id}.nodes[{index}].config.max_iterations",
                        code="LIMIT_EXCEEDED",
                        message=f"Review iteration limit exceeds {max_review_iterations}",
                    )
                )
    return errors


def _validate_references(
    workflows: dict[str, WorkflowDefinition],
    graph: dict[str, list[str]],
    maximum_depth: int,
) -> list[ValidationIssue]:
    errors: list[ValidationIssue] = []
    for parent_id, references in graph.items():
        parent = workflows[parent_id]
        for child_id in references:
            if child_id not in workflows:
                errors.append(
                    ValidationIssue(
                        path=f"workflows.{parent_id}.nodes",
                        code="MISSING_SUBWORKFLOW",
                        message=f"Workflow '{child_id}' does not exist",
                    )
                )
        for index, node in enumerate(parent.nodes):
            child_roles: list[tuple[str, dict[str, str], str]] = []
            output_mapping: dict[str, str] = {}
            if isinstance(node, SubworkflowNode):
                child_roles = [(node.config.workflow_id, node.config.inputs, "inputs")]
                output_mapping = node.config.output_mapping
            elif isinstance(node, ReviewLoopNode):
                child_roles = [(node.config.initial_workflow_id, node.config.inputs, "inputs")]
                output_mapping = node.config.output_mapping
                if node.config.revision_workflow_id:
                    child_roles.append(
                        (
                            node.config.revision_workflow_id,
                            node.config.revision_inputs,
                            "revision_inputs",
                        )
                    )
            for child_id, input_mapping, mapping_field in child_roles:
                child = workflows.get(child_id)
                if child is None:
                    continue
                for input_name, definition in child.inputs.items():
                    if (
                        definition.required
                        and definition.default is None
                        and input_name not in input_mapping
                    ):
                        errors.append(
                            ValidationIssue(
                                path=(
                                    f"workflows.{parent_id}.nodes[{index}].config.{mapping_field}"
                                ),
                                code="MISSING_CHILD_INPUT",
                                message=f"Required child input '{input_name}' is not mapped",
                            )
                        )
                for output_name in output_mapping:
                    if output_name not in child.outputs:
                        errors.append(
                            ValidationIssue(
                                path=f"workflows.{parent_id}.nodes[{index}].config.output_mapping.{output_name}",
                                code="INVALID_OUTPUT_MAPPING",
                                message=f"Child workflow has no output '{output_name}'",
                            )
                        )
                if isinstance(node, ReviewLoopNode):
                    if any(
                        isinstance(child_node, (HumanFeedbackNode, ReviewLoopNode))
                        for child_node in child.nodes
                    ):
                        errors.append(
                            ValidationIssue(
                                path=f"workflows.{parent_id}.nodes[{index}]",
                                code="NESTED_REVIEW_CHECKPOINT",
                                message=f"Review child '{child_id}' contains a feedback checkpoint",
                            )
                        )

    stack: list[str] = []

    def visit(workflow_id: str, depth: int) -> None:
        if workflow_id in stack:
            cycle = " -> ".join([*stack[stack.index(workflow_id) :], workflow_id])
            errors.append(
                ValidationIssue(
                    path=f"workflows.{workflow_id}",
                    code="RECURSIVE_SUBWORKFLOW",
                    message=f"Recursive workflow reference: {cycle}",
                )
            )
            return
        if depth > maximum_depth:
            errors.append(
                ValidationIssue(
                    path=f"workflows.{workflow_id}",
                    code="MAX_SUBWORKFLOW_DEPTH",
                    message=f"Workflow reference depth exceeds {maximum_depth}",
                )
            )
            return
        if workflow_id not in workflows:
            return
        stack.append(workflow_id)
        for child_id in graph.get(workflow_id, []):
            visit(child_id, depth + 1)
        stack.pop()

    for workflow_id in sorted(workflows):
        visit(workflow_id, 1)
    return errors


def validate_trigger_inputs(workflow: WorkflowDefinition, values: dict[str, Any]) -> dict[str, Any]:
    unknown = set(values) - set(workflow.inputs)
    if unknown:
        raise ValueError(f"Unknown workflow inputs: {', '.join(sorted(unknown))}")
    result: dict[str, Any] = {}
    for name, definition in workflow.inputs.items():
        if name in values:
            value = values[name]
        elif definition.default is not None:
            value = definition.default
        elif definition.required:
            raise ValueError(f"Required workflow input '{name}' is missing")
        else:
            continue
        if definition.type in {"integer", "number"} and isinstance(value, bool):
            raise ValueError(f"Workflow input '{name}' has the wrong type")
        correct_type = (
            (definition.type == "string" and isinstance(value, str))
            or (definition.type == "integer" and isinstance(value, int))
            or (definition.type == "number" and isinstance(value, (int, float)))
            or (definition.type == "boolean" and isinstance(value, bool))
        )
        if not correct_type:
            raise ValueError(f"Workflow input '{name}' has the wrong type")
        result[name] = value
    return result
