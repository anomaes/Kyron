from __future__ import annotations

from typing import Any


def bash_node(node_id: str, command: str = "true") -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "bash",
        "label": node_id,
        "config": {"command": command},
        "position": {"x": 0, "y": 0},
    }


def workflow(
    workflow_id: str = "root",
    *,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": workflow_id,
        "name": workflow_id,
        "description": "test workflow",
        "version": 2,
        "created_by": "test@example.com",
        "inputs": inputs or {},
        "outputs": outputs or {},
        "variables": {},
        "nodes": nodes or [bash_node("start")],
        "edges": edges or [],
        "settings": {},
    }


def edge(source: str, target: str, edge_id: str = "e1") -> dict[str, Any]:
    return {"id": edge_id, "source": source, "target": target, "condition": None}
