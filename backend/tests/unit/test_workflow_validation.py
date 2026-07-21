from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from backend.engine.validation import (
    parse_workflow,
    validate_trigger_inputs,
    validate_workflow_bundle,
)
from backend.schemas.workflow import WorkflowDefinition, WorkflowValidationResponse
from backend.tests.fixtures.workflows import bash_node, edge, workflow


def parsed(data: dict[str, Any]) -> WorkflowDefinition:
    result, errors = parse_workflow(data)
    assert not errors
    assert result is not None
    return result


def test_workflow_tags_are_validated_and_preserved() -> None:
    definition = parsed(workflow(tags=["implementation", "team-platform"]))
    assert definition.tags == ["implementation", "team-platform"]

    invalid, errors = parse_workflow(workflow(tags=["Not valid"]))
    assert invalid is None
    assert any(issue.path == "workflow.tags.0" for issue in errors)

    duplicate, errors = parse_workflow(workflow(tags=["implementation", "implementation"]))
    assert duplicate is None
    assert any(issue.path == "workflow.tags" for issue in errors)


def test_pi_defaults_and_prompt_overrides_are_parsed() -> None:
    data = workflow(
        nodes=[
            {
                "id": "agent",
                "type": "prompt",
                "label": "agent",
                "config": {
                    "prompt": "Ship it",
                    "model": "node-model",
                    "skill": ".agents/skills/node/SKILL.md",
                },
            }
        ]
    )
    data["settings"] = {
        "pi": {
            "provider": "anthropic",
            "model": "workflow-model",
            "skill": ".agents/skills/workflow/SKILL.md",
        }
    }
    definition = parsed(data)
    assert definition.settings.pi.model == "workflow-model"
    node = definition.nodes[0]
    assert node.type == "prompt"
    assert node.config.skill == ".agents/skills/node/SKILL.md"


def test_gate_nodes_default_to_the_triggerer_approval_policy() -> None:
    human = parsed(
        workflow(
            nodes=[
                {
                    "id": "review",
                    "type": "human_feedback",
                    "label": "Review",
                    "config": {},
                }
            ]
        )
    )
    human_node = human.nodes[0]
    assert human_node.type == "human_feedback"
    assert human_node.config.approval_policy == "default"

    loop = parsed(
        workflow(
            nodes=[
                {
                    "id": "review",
                    "type": "review_loop",
                    "label": "Review",
                    "config": {"initial_workflow_id": "child"},
                }
            ]
        )
    )
    loop_node = loop.nodes[0]
    assert loop_node.type == "review_loop"
    assert loop_node.config.approval_policy == "default"


@pytest.mark.parametrize("skill", ["../outside/SKILL.md", "/absolute/SKILL.md"])
def test_pi_skill_paths_cannot_escape_repository(skill: str) -> None:
    data = workflow()
    data["settings"] = {"pi": {"skill": skill}}
    _, errors = parse_workflow(data)
    assert any("inside the repository" in issue.message for issue in errors)


def codes(report: WorkflowValidationResponse) -> set[str]:
    return {issue.code for issue in report.errors}


def test_valid_simple_dag() -> None:
    definition = parsed(
        workflow(
            nodes=[bash_node("start"), bash_node("finish")],
            edges=[edge("start", "finish")],
        )
    )
    report = validate_workflow_bundle("root", {"root": definition})
    assert report.valid


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda data: data["nodes"].append(bash_node("start")), "DUPLICATE_NODE_ID"),
        (
            lambda data: data["edges"].append(edge("start", "finish", "e1")),
            "DUPLICATE_EDGE_ID",
        ),
        (
            lambda data: data["edges"].append(edge("missing", "finish", "e2")),
            "MISSING_NODE_REFERENCE",
        ),
        (lambda data: data["nodes"].append(bash_node("orphan")), "ORPHANED_NODE"),
    ],
)
def test_structural_errors(mutation: Callable[[dict[str, Any]], None], code: str) -> None:
    data = workflow(
        nodes=[bash_node("start"), bash_node("finish")],
        edges=[edge("start", "finish")],
    )
    mutation(data)
    report = validate_workflow_bundle("root", {"root": parsed(data)})
    assert code in codes(report)


def test_direct_graph_cycle_is_rejected() -> None:
    definition = parsed(
        workflow(
            nodes=[bash_node("a"), bash_node("b")],
            edges=[edge("a", "b", "e1"), edge("b", "a", "e2")],
        )
    )
    assert "GRAPH_CYCLE" in codes(validate_workflow_bundle("root", {"root": definition}))


def test_schema_rejects_unknown_condition_and_script_traversal() -> None:
    data = workflow(nodes=[bash_node("start"), bash_node("finish")])
    data["edges"] = [
        {
            "id": "e1",
            "source": "start",
            "target": "finish",
            "condition": {"type": "surprise", "value": 1},
        }
    ]
    _, errors = parse_workflow(data)
    assert errors

    data = workflow(
        nodes=[
            {
                "id": "script",
                "type": "script",
                "label": "script",
                "config": {"script": "../escape.py"},
            }
        ]
    )
    _, errors = parse_workflow(data)
    assert any("inside the repository" in item.message for item in errors)


def test_missing_and_recursive_subworkflows_are_rejected() -> None:
    root = parsed(
        workflow(
            nodes=[
                {
                    "id": "child",
                    "type": "subworkflow",
                    "label": "child",
                    "config": {"workflow_id": "missing"},
                }
            ]
        )
    )
    assert "MISSING_SUBWORKFLOW" in codes(validate_workflow_bundle("root", {"root": root}))

    child = parsed(
        workflow(
            "missing",
            nodes=[
                {
                    "id": "back",
                    "type": "subworkflow",
                    "label": "back",
                    "config": {"workflow_id": "root"},
                }
            ],
        )
    )
    assert "RECURSIVE_SUBWORKFLOW" in codes(
        validate_workflow_bundle("root", {"root": root, "missing": child})
    )


def test_child_inputs_outputs_and_review_checkpoint_are_validated() -> None:
    child = parsed(
        workflow(
            "child",
            inputs={"TASK": {"type": "string", "required": True}},
            outputs={"RESULT": {"type": "string", "source": "${VALUE}"}},
        )
    )
    root = parsed(
        workflow(
            nodes=[
                {
                    "id": "call",
                    "type": "subworkflow",
                    "label": "call",
                    "config": {
                        "workflow_id": "child",
                        "output_mapping": {"UNKNOWN": "PARENT"},
                    },
                }
            ]
        )
    )
    report = validate_workflow_bundle("root", {"root": root, "child": child})
    assert {"MISSING_CHILD_INPUT", "INVALID_OUTPUT_MAPPING"} <= codes(report)

    checkpoint_child = parsed(
        workflow(
            "child",
            nodes=[
                {
                    "id": "wait",
                    "type": "human_feedback",
                    "label": "wait",
                    "config": {"approval_policy": "review"},
                }
            ],
        )
    )
    review_root = parsed(
        workflow(
            nodes=[
                {
                    "id": "review",
                    "type": "review_loop",
                    "label": "review",
                    "config": {
                        "approval_policy": "review",
                        "initial_workflow_id": "child",
                    },
                }
            ]
        )
    )
    assert "NESTED_REVIEW_CHECKPOINT" in codes(
        validate_workflow_bundle("root", {"root": review_root, "child": checkpoint_child})
    )


def test_reference_depth_limit_is_enforced() -> None:
    workflows = {}
    for index in range(4):
        workflow_id = f"level{index}"
        nodes = [bash_node("done")]
        if index < 3:
            nodes = [
                {
                    "id": "next",
                    "type": "subworkflow",
                    "label": "next",
                    "config": {"workflow_id": f"level{index + 1}"},
                }
            ]
        workflows[workflow_id] = parsed(workflow(workflow_id, nodes=nodes))
    report = validate_workflow_bundle("level0", workflows, max_subworkflow_depth=3)
    assert "MAX_SUBWORKFLOW_DEPTH" in codes(report)


def test_typed_trigger_inputs_apply_defaults_and_reject_wrong_types() -> None:
    definition = parsed(
        workflow(
            inputs={
                "TASK": {"type": "string", "required": True},
                "COUNT": {"type": "integer", "default": 2},
            }
        )
    )
    assert validate_trigger_inputs(definition, {"TASK": "ship"}) == {
        "TASK": "ship",
        "COUNT": 2,
    }
    with pytest.raises(ValueError, match="wrong type"):
        validate_trigger_inputs(definition, {"TASK": 2})
