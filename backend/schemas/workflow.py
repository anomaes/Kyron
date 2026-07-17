from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

IDENTIFIER_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"
Identifier = Annotated[str, Field(pattern=IDENTIFIER_PATTERN, min_length=1, max_length=255)]
TemplateValue = str | int | float | bool


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Position(StrictModel):
    x: float = 0
    y: float = 0


class WorkflowInput(StrictModel):
    type: Literal["string", "integer", "number", "boolean"] = "string"
    required: bool = False
    default: TemplateValue | None = None
    description: str | None = None


class WorkflowOutput(StrictModel):
    type: Literal["string", "integer", "number", "boolean"] = "string"
    source: str
    description: str | None = None


ComparisonOperator = Literal[
    "equals",
    "not_equals",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
]


class ExitCodeCondition(StrictModel):
    type: Literal["exit_code"]
    operator: ComparisonOperator
    value: int


class OutputContainsCondition(StrictModel):
    type: Literal["output_contains"]
    value: str
    stream: Literal["stdout", "stderr", "combined"] = "stdout"


class FileExistsCondition(StrictModel):
    type: Literal["file_exists"]
    value: str

    @field_validator("value")
    @classmethod
    def path_must_be_relative(cls, value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError("File condition path must remain inside the repository")
        return value


class VariableCondition(StrictModel):
    type: Literal["variable"]
    name: Identifier
    operator: ComparisonOperator
    value: TemplateValue


EdgeCondition = Annotated[
    ExitCodeCondition | OutputContainsCondition | FileExistsCondition | VariableCondition,
    Field(discriminator="type"),
]


class Edge(StrictModel):
    id: Identifier
    source: Identifier
    target: Identifier
    condition: EdgeCondition | None = None


class BashConfig(StrictModel):
    command: str = Field(min_length=1)
    timeout: int | None = Field(default=None, gt=0)
    allow_failure: bool = False
    shell: str = "/bin/bash"


class ScriptConfig(StrictModel):
    script: str = Field(min_length=1)
    python: str = "python3"
    args: list[str] = Field(default_factory=list)
    timeout: int | None = Field(default=None, gt=0)
    allow_failure: bool = False

    @field_validator("script")
    @classmethod
    def script_must_be_relative(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Script path must remain inside the repository")
        return value


class PromptConfig(StrictModel):
    prompt: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = None
    timeout: int | None = Field(default=None, gt=0)
    allow_failure: bool = False
    project_trust: Literal["never"] = "never"


class HumanFeedbackConfig(StrictModel):
    commit_message: str = "Checkpoint: awaiting review"
    mr_title: str | None = None
    mr_description: str | None = None
    allow_comment_feedback: bool = True
    allow_approval: bool = True


class SubworkflowConfig(StrictModel):
    workflow_id: Identifier
    inputs: dict[Identifier, str] = Field(default_factory=dict)
    output_mapping: dict[Identifier, Identifier] = Field(default_factory=dict)
    allow_failure: bool = False


class ReviewLoopConfig(StrictModel):
    initial_workflow_id: Identifier
    revision_workflow_id: Identifier | None = None
    inputs: dict[Identifier, str] = Field(default_factory=dict)
    revision_inputs: dict[Identifier, str] = Field(default_factory=dict)
    commit_message: str = "Checkpoint: review iteration ${REVIEW_ITERATION}"
    mr_title: str | None = None
    mr_description: str | None = None
    max_iterations: int | None = Field(default=None, gt=0)
    output_mapping: dict[Identifier, Identifier] = Field(default_factory=dict)


class NodeCommon(StrictModel):
    id: Identifier
    label: str = Field(min_length=1, max_length=255)
    join: Literal["and", "or"] = "and"
    position: Position = Field(default_factory=Position)


class BashNode(NodeCommon):
    type: Literal["bash"]
    config: BashConfig


class ScriptNode(NodeCommon):
    type: Literal["script"]
    config: ScriptConfig


class PromptNode(NodeCommon):
    type: Literal["prompt"]
    config: PromptConfig


class HumanFeedbackNode(NodeCommon):
    type: Literal["human_feedback"]
    config: HumanFeedbackConfig


class SubworkflowNode(NodeCommon):
    type: Literal["subworkflow"]
    config: SubworkflowConfig


class ReviewLoopNode(NodeCommon):
    type: Literal["review_loop"]
    config: ReviewLoopConfig


WorkflowNode = Annotated[
    BashNode | ScriptNode | PromptNode | HumanFeedbackNode | SubworkflowNode | ReviewLoopNode,
    Field(discriminator="type"),
]


class WorkflowSettings(StrictModel):
    auto_commit_after_wave: bool = True
    wave_commit_message_template: str = "workflow(${WORKFLOW_ID}): wave ${WAVE_INDEX}"
    final_commit_message_template: str = "workflow(${WORKFLOW_ID}): complete run ${RUN_ID}"
    mr_title_template: str = "Workflow: ${WORKFLOW_NAME} (${RUN_ID_SHORT})"
    mr_description_template: str = (
        "Automated workflow run triggered by ${USER_NAME}.\n\n"
        "Workflow: ${WORKFLOW_NAME}\nBase commit: ${BASE_COMMIT_SHA}\nRun: ${RUN_ID}"
    )
    timeout_per_node_seconds: int = Field(default=1800, gt=0)
    max_review_iterations: int = Field(default=5, gt=0)
    max_subworkflow_depth: int = Field(default=8, gt=0)
    max_output_variable_bytes: int = Field(default=65536, ge=1024)
    propagate_skips: bool = False


class WorkflowDefinition(StrictModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    version: Literal[2] = 2
    created_by: str
    inputs: dict[Identifier, WorkflowInput] = Field(default_factory=dict)
    outputs: dict[Identifier, WorkflowOutput] = Field(default_factory=dict)
    variables: dict[Identifier, TemplateValue] = Field(default_factory=dict)
    nodes: list[WorkflowNode]
    edges: list[Edge] = Field(default_factory=list)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)


class ValidationIssue(BaseModel):
    path: str
    code: str
    message: str


class WorkflowValidationResponse(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


class WorkflowValidationRequest(BaseModel):
    workflow: dict[str, Any]
    proposed_related_workflows: dict[str, dict[str, Any]] = Field(default_factory=dict)


class WorkflowBundle(BaseModel):
    snapshot_version: Literal[1] = 1
    base_commit_sha: str = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")
    root_workflow_id: Identifier
    workflows: dict[Identifier, WorkflowDefinition]
    reference_graph: dict[Identifier, list[Identifier]]
