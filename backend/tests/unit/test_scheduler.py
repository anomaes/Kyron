from __future__ import annotations

from typing import Any

from backend.engine.scheduler import DagScheduler, LogicalStatus
from backend.engine.validation import parse_workflow
from backend.tests.fixtures.workflows import bash_node, edge, workflow


def scheduler_for(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> DagScheduler:
    definition, errors = parse_workflow(workflow(nodes=nodes, edges=edges))
    assert not errors and definition is not None
    return DagScheduler(definition)


def test_linear_and_parallel_ready_nodes_are_deterministic() -> None:
    scheduler = scheduler_for(
        [bash_node("start"), bash_node("b"), bash_node("a")],
        [edge("start", "a", "e1"), edge("start", "b", "e2")],
    )
    first = scheduler.next({}, {})
    assert [node.id for node in first.nodes] == ["start"]
    second = scheduler.next({"start": LogicalStatus.SUCCESS}, {"e1": True, "e2": True})
    assert [node.id for node in second.nodes] == ["a", "b"]


def test_and_join_runs_with_one_true_and_skips_with_all_false() -> None:
    join = bash_node("join")
    join["join"] = "and"
    scheduler = scheduler_for(
        [bash_node("left"), bash_node("right"), join],
        [edge("left", "join", "left_join"), edge("right", "join", "right_join")],
    )
    statuses = {"left": LogicalStatus.SUCCESS, "right": LogicalStatus.SUCCESS}
    decision = scheduler.next(statuses, {"left_join": True, "right_join": False})
    assert [node.id for node in decision.nodes] == ["join"]
    skipped = scheduler.next(statuses, {"left_join": False, "right_join": False})
    assert skipped.skipped_node_ids == ["join"]


def test_or_join_is_ready_after_first_true_edge() -> None:
    join = bash_node("join")
    join["join"] = "or"
    scheduler = scheduler_for(
        [bash_node("left"), bash_node("right"), join],
        [edge("left", "join", "left_join"), edge("right", "join", "right_join")],
    )
    decision = scheduler.next(
        {"left": LogicalStatus.SUCCESS, "right": LogicalStatus.RUNNING},
        {"left_join": True},
    )
    assert [node.id for node in decision.nodes] == ["join"]


def test_control_nodes_are_isolated_after_process_nodes() -> None:
    control = {
        "id": "child",
        "type": "subworkflow",
        "label": "child",
        "config": {"workflow_id": "other"},
    }
    scheduler = scheduler_for([bash_node("process"), control], [])
    first = scheduler.next({}, {})
    assert [node.id for node in first.nodes] == ["process"]
    assert not first.control_boundary
    second = scheduler.next({"process": LogicalStatus.SUCCESS}, {})
    assert [node.id for node in second.nodes] == ["child"]
    assert second.control_boundary


def test_running_subworkflow_is_ready_for_continuation() -> None:
    child = {
        "id": "child",
        "type": "subworkflow",
        "label": "child",
        "config": {"workflow_id": "other"},
    }
    scheduler = scheduler_for([child, bash_node("after")], [edge("child", "after")])

    decision = scheduler.next({"child": LogicalStatus.RUNNING}, {})

    assert [node.id for node in decision.nodes] == ["child"]
    assert decision.control_boundary
