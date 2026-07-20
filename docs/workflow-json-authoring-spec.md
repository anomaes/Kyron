# Kyron workflow JSON authoring specification

This document is the authoring contract for repository workflow files consumed by
the current Kyron implementation. It is intentionally written so that a person or
an LLM can create a workflow without reading backend source code.

The Pydantic models in `backend/schemas/workflow.py` and the validators in
`backend/engine/validation.py` remain authoritative if this document and the code
ever disagree. The broader product behavior is defined in
`workflow_orchestration_engine_spec.md`.

## 1. LLM output contract

When asked to create or change a workflow, produce one or more complete JSON files.
For every file:

1. Store it at `.workflowEngine/<id>.json`.
2. Make the filename stem exactly equal to the root `id` value, including case.
3. Emit strict JSON: double-quoted keys and strings, no comments, no trailing commas,
   and no Markdown fences when raw file content is requested.
4. Set `version` to `2`.
5. Use only fields documented here. Unknown fields are validation errors at every
   level of the document.
6. Use a directed acyclic graph. Never model repetition with a back edge; use a
   `review_loop` node.
7. Include every transitively referenced child workflow as a separate file unless it
   already exists in the target repository.
8. Never put credentials, tokens, authenticated URLs, or other secrets in workflow
   JSON.

Prefer explicit fields and canonical defaults in generated files even where a field
may be omitted. This makes LLM output easier to review and less dependent on implicit
defaults.

## 2. Lexical types and naming

### 2.1 Identifier

Workflow IDs, node IDs, edge IDs, input names, output names, variable names, and
mapping names use this pattern:

```text
^[A-Za-z][A-Za-z0-9_]*$
```

They are 1 to 255 characters long, start with an ASCII letter, and contain only
ASCII letters, digits, and underscores. They are case-sensitive. Hyphens, spaces,
dots, and leading underscores are invalid.

Examples: `implement_review`, `RunTests2`, `TASK`, `NODE_RESULT`.

### 2.2 Template value

A template value is a JSON string, integer, number, or boolean. It is never an array,
object, or `null`, except that an input's `default` may explicitly be `null`.

### 2.3 Tag

A tag is 1 to 64 characters and matches:

```text
^[a-z0-9][a-z0-9._-]*$
```

Tags must be unique within a workflow. A workflow may contain at most 32 tags. Tags
are catalog metadata and do not change execution.

## 3. Root workflow object

The root object has this shape. Fields marked required must be present.

| Field | Type | Required | Default / constraint |
|---|---|---:|---|
| `id` | identifier | yes | Must equal the filename stem. |
| `name` | string | yes | 1 to 255 characters. |
| `description` | string | no | `""` |
| `version` | integer | no | Must be exactly `2`; write it explicitly. |
| `created_by` | string | yes | Conventionally an email address; no format validation. |
| `tags` | tag array | no | `[]`; unique; at most 32. |
| `inputs` | object | no | `{}`; keys are identifiers. |
| `outputs` | object | no | `{}`; keys are identifiers. |
| `variables` | object | no | `{}`; identifier keys and template values. |
| `nodes` | node array | yes | Must contain at least one node after semantic validation. |
| `edges` | edge array | no | `[]` |
| `settings` | settings object | no | `{}` applies project and engine defaults. |

Minimal valid workflow:

```json
{
  "id": "hello_world",
  "name": "Hello world",
  "description": "A minimal Kyron workflow.",
  "version": 2,
  "created_by": "automation@example.com",
  "tags": ["example"],
  "inputs": {},
  "outputs": {},
  "variables": {},
  "nodes": [
    {
      "id": "hello",
      "type": "bash",
      "label": "Print greeting",
      "join": "and",
      "config": {
        "command": "echo 'Hello from Kyron'",
        "allow_failure": false,
        "shell": "/bin/bash"
      },
      "position": { "x": 100, "y": 100 }
    }
  ],
  "edges": [],
  "settings": {}
}
```

### 3.1 Pi defaults and inheritance

Pi provider, model, and skill selection is resolved independently for every prompt
node. Each non-null field is taken from the most specific scope that defines it:

```text
prompt node config -> workflow settings.pi -> project pi defaults -> Pi default
```

Because resolution is field-by-field, a node may override only `model` while retaining
the workflow's `provider` and the project's `skill`. `null` and omitted fields inherit
from the next scope. Project defaults are stored in the Kyron project registry and are
copied into the immutable run snapshot when a run is created.

The same Pi settings shape is used at project and workflow scope:

```json
{
  "provider": "anthropic",
  "model": "anthropic/claude-sonnet-4-5",
  "skill": ".agents/skills/implementation/SKILL.md"
}
```

All fields are optional. `provider` and `model` are passed to Pi as `--provider` and
`--model`. `skill` names a Markdown skill manifest or skill directory relative to the
repository root. A directory must contain `SKILL.md`; a direct manifest must declare a
Pi-compatible `name` in its YAML frontmatter. The resolved file must remain inside the
run worktree. Kyron loads that one skill explicitly and invokes its `/skill:<name>`
command. This works with Pi's project trust disabled and ties the skill contents to
the run's exact base commit.

Configure project defaults through `PUT /projects/<project_uuid>/pi`. Configure
workflow defaults under `settings.pi`; configure a prompt-node override with its
`config.provider`, `config.model`, and `config.skill` fields.

## 4. Inputs, variables, templates, and outputs

### 4.1 Inputs

Each entry in `inputs` has the following fields:

| Field | Type | Required | Default / constraint |
|---|---|---:|---|
| `type` | `string`, `integer`, `number`, or `boolean` | no | `string` |
| `required` | boolean | no | `false` |
| `default` | template value or `null` | no | `null` |
| `description` | string or `null` | no | `null` |

Example:

```json
{
  "inputs": {
    "TASK": {
      "type": "string",
      "required": true,
      "description": "The change to implement"
    },
    "RETRIES": {
      "type": "integer",
      "required": false,
      "default": 2
    }
  }
}
```

Root trigger inputs are type-checked. Booleans are not accepted as integers or
numbers. Unknown trigger input names are rejected. If `required` is true and
`default` is `null` or absent, the caller must supply the input.

Always make the JSON type of a non-null default agree with the declared `type`.

### 4.2 Variables

`variables` defines non-secret public context defaults:

```json
{
  "variables": {
    "TARGET_DIR": "src/",
    "STRICT": true,
    "RETRY_COUNT": 2
  }
}
```

Variable keys are identifiers. Values are strings, integers, numbers, or booleans.
Do not define credentials here.

### 4.3 Public template expansion

Supported template syntax is exactly `${NAME}`, where `NAME` matches:

```text
[A-Za-z_][A-Za-z0-9_]*
```

Every referenced public variable must exist when the field is expanded. An unknown
`${NAME}` fails execution; it is not left unchanged. Expansion converts the value to
text.

Templates are expanded in these locations:

- Bash `config.command`.
- Every Script `config.args` item.
- Prompt `config.prompt`.
- Sub-workflow and review-loop input mapping values.
- Workflow output `source` values.
- Checkpoint, wave, final-commit, and merge-request templates.

Templates are not expanded in IDs, labels, paths, `script`, `python`, `shell`,
`provider`, `model`, or `skill`.

Secrets are injected only into subprocess environments. In a Bash command use the
shell's native `$SECRET_NAME` form for a credential. `${SECRET_NAME}` asks Kyron for
a public variable and fails if only a secret exists. Script and prompt templates
cannot expand secrets.

Public built-ins available during a normal run are:

| Variable | Meaning |
|---|---|
| `RUN_ID` | Full run UUID. |
| `RUN_ID_SHORT` | First eight hex characters of the run UUID. |
| `ROOT_WORKFLOW_ID` | Root workflow ID. |
| `WORKFLOW_ID` | Current invocation's workflow ID. |
| `WORKFLOW_NAME` | Current invocation's workflow name. |
| `INVOCATION_ID` | Current invocation UUID. |
| `INVOCATION_PATH` | Current invocation path, for example `root/child`. |
| `PROJECT_ID` | Project UUID. |
| `PROJECT_NAME` | Project display name. |
| `BASE_REF` | Base ref selected for the run. |
| `BASE_COMMIT_SHA` | Exact pinned commit SHA. |
| `BRANCH` | Run branch name. |
| `WORKTREE_PATH` | Absolute run worktree path. |
| `RUN_DATA_PATH` | Absolute output-data path. |
| `USER_NAME` | Triggering user's display name. |
| `USER_EMAIL` | Triggering user's email. |
| `CODE_HOST_PROVIDER` | Active run provider: `gitlab` or `github`. |
| `PROVIDER_USER_ID` | Triggering user's provider ID as text. |
| `PROVIDER_USERNAME` | Triggering user's provider username. |
| `GITLAB_USER_ID` | Legacy alias populated only for GitLab runs. |
| `GITLAB_USERNAME` | Legacy alias populated only for GitLab runs. |
| `REVIEW_ITERATION` | Current review-loop iteration when inside a review loop. |
| `FEEDBACK` | Latest feedback text after feedback has been submitted. |
| `FEEDBACK_TYPE` | `comment` or `approval` after feedback has been submitted. |
| `FEEDBACK_AUTHOR` | Latest feedback author's username. |

`WAVE_INDEX` is additionally available while expanding
`wave_commit_message_template`.

Do not rely on a feedback variable before the first feedback event. In particular,
put `${FEEDBACK}` in `revision_inputs`, not initial `inputs`.

### 4.4 Process-node output variables

After a Bash, Script, or Prompt node succeeds, Kyron adds these public variables:

```text
NODE_<node_id>_EXIT_CODE
NODE_<node_id>_STDOUT
NODE_<node_id>_STDERR
NODE_<node_id>_STDOUT_PATH
NODE_<node_id>_STDERR_PATH
```

For a node with ID `tests`, use `${NODE_tests_EXIT_CODE}`. Output text is a bounded
preview; use the path variable when the full file is needed. Prompt stdout is Pi's raw
JSONL event stream.

### 4.5 Declared outputs

Each `outputs` entry has this shape:

| Field | Type | Required | Default / constraint |
|---|---|---:|---|
| `type` | `string`, `integer`, `number`, or `boolean` | no | `string` |
| `source` | string | yes | Public template expanded at invocation completion. |
| `description` | string or `null` | no | `null` |

Example:

```json
{
  "outputs": {
    "TEST_EXIT_CODE": {
      "type": "string",
      "source": "${NODE_tests_EXIT_CODE}",
      "description": "Exit code rendered as text"
    }
  }
}
```

The current runtime expands every output source to a string and does not enforce the
declared output type. Declare generated outputs as `string` unless a consumer uses the
type only as catalog metadata.

## 5. Common node object

Every node is one of the six discriminated node types below and contains:

| Field | Type | Required | Default / constraint |
|---|---|---:|---|
| `id` | identifier | yes | Unique within the workflow. |
| `type` | node-type literal | yes | Selects the exact `config` schema. |
| `label` | string | yes | 1 to 255 characters. |
| `join` | `and` or `or` | no | `and` |
| `config` | object | yes | Exact shape depends on `type`. |
| `position` | `{ "x": number, "y": number }` | no | Both coordinates default to `0`. |

`position` affects only builder layout. `join` affects only nodes with incoming edges.

## 6. Node types

### 6.1 Bash

```json
{
  "id": "tests",
  "type": "bash",
  "label": "Run tests",
  "join": "and",
  "config": {
    "command": "python -m pytest ${TEST_ARGS}",
    "timeout": 1800,
    "allow_failure": false,
    "shell": "/bin/bash"
  },
  "position": { "x": 360, "y": 100 }
}
```

| Config field | Type | Required | Default / constraint |
|---|---|---:|---|
| `command` | non-empty string | yes | Public templates are expanded. |
| `timeout` | positive integer or `null` | no | Workflow default timeout. |
| `allow_failure` | boolean | no | `false` |
| `shell` | string | no | `/bin/bash` |

The command runs as `[shell, "-lc", expanded_command]` in the worktree. A non-zero
exit or timeout fails the wave unless `allow_failure` is true.

### 6.2 Script

```json
{
  "id": "validate",
  "type": "script",
  "label": "Validate result",
  "join": "and",
  "config": {
    "script": "scripts/validate.py",
    "python": "python3",
    "args": ["--target", "${TARGET_DIR}"],
    "timeout": 900,
    "allow_failure": false
  },
  "position": { "x": 620, "y": 100 }
}
```

| Config field | Type | Required | Default / constraint |
|---|---|---:|---|
| `script` | non-empty string | yes | Relative repository path; no `..`; must exist at run time. |
| `python` | string | no | `python3` |
| `args` | string array | no | `[]`; public templates expand per item. |
| `timeout` | positive integer or `null` | no | Workflow default timeout. |
| `allow_failure` | boolean | no | `false` |

The process runs without a shell as `[python, absolute_script_path, ...args]` in the
worktree.

### 6.3 Prompt

```json
{
  "id": "implement",
  "type": "prompt",
  "label": "Implement task",
  "join": "and",
  "config": {
    "prompt": "Implement this task and run relevant tests: ${TASK}",
    "provider": "anthropic",
    "model": "anthropic/claude-sonnet-4-5",
    "skill": ".agents/skills/implementation/SKILL.md",
    "timeout": 1800,
    "allow_failure": false,
    "project_trust": "never"
  },
  "position": { "x": 360, "y": 100 }
}
```

| Config field | Type | Required | Default / constraint |
|---|---|---:|---|
| `prompt` | non-empty string | yes | Public templates are expanded. |
| `provider` | string or `null` | no | `null`; omitted from Pi command. |
| `model` | string or `null` | no | `null`; omitted from Pi command. |
| `skill` | string or `null` | no | `null`; repository-relative skill file or directory. |
| `timeout` | positive integer or `null` | no | Workflow default timeout. |
| `allow_failure` | boolean | no | `false` |
| `project_trust` | `never` | no | Must be `never`. |

Each null or omitted Pi field inherits from `settings.pi`, then from the project. If
no scope supplies a provider or model, Pi selects its configured default. If `skill`
resolves to a value, the path must exist at the run's pinned commit; a missing,
escaping, or malformed skill fails the node before Pi starts.

Do not invent provider, model, or skill values. Use values supplied by the user or
already used by the repository; otherwise omit them.

### 6.4 Human feedback

```json
{
  "id": "review",
  "type": "human_feedback",
  "label": "Await review",
  "join": "and",
  "config": {
    "commit_message": "Checkpoint: awaiting review",
    "mr_title": "Review ${WORKFLOW_NAME}",
    "mr_description": "Approve to continue or submit feedback.",
    "allow_comment_feedback": true,
    "allow_approval": true
  },
  "position": { "x": 620, "y": 100 }
}
```

| Config field | Type | Required | Default |
|---|---|---:|---|
| `commit_message` | string | no | `Checkpoint: awaiting review` |
| `mr_title` | string or `null` | no | Workflow MR title template. |
| `mr_description` | string or `null` | no | Workflow MR description template. |
| `allow_comment_feedback` | boolean | no | `true` |
| `allow_approval` | boolean | no | `true` |

This node checkpoints, pushes, opens or updates the provider change request, and pauses.
Approval or feedback from the triggering provider user completes it. It does not repeat prior
nodes; use `review_loop` for revision cycles.

### 6.5 Sub-workflow

```json
{
  "id": "run_child",
  "type": "subworkflow",
  "label": "Run validation workflow",
  "join": "and",
  "config": {
    "workflow_id": "validate_change",
    "inputs": {
      "TARGET_DIR": "${TARGET_DIR}"
    },
    "output_mapping": {
      "RESULT": "VALIDATION_RESULT"
    },
    "allow_failure": false
  },
  "position": { "x": 620, "y": 100 }
}
```

| Config field | Type | Required | Default / meaning |
|---|---|---:|---|
| `workflow_id` | identifier | yes | Child workflow file ID. |
| `inputs` | identifier-to-string object | no | `{}`; child input name to parent template. |
| `output_mapping` | identifier-to-identifier object | no | `{}`; child output name to new parent public-variable name. |
| `allow_failure` | boolean | no | `false` |

Mapping direction is important:

```text
inputs:         CHILD_INPUT  -> "parent template"
output_mapping: CHILD_OUTPUT -> PARENT_VARIABLE
```

Every required child input without a non-null default must be present in `inputs`.
Every output-mapping key must be declared by the child workflow. The child executes in
the same run worktree and branch.

### 6.6 Review loop

```json
{
  "id": "implementation_review",
  "type": "review_loop",
  "label": "Implement and review",
  "join": "and",
  "config": {
    "initial_workflow_id": "implement_change",
    "revision_workflow_id": "revise_change",
    "inputs": {
      "TASK": "${TASK}"
    },
    "revision_inputs": {
      "TASK": "${TASK}",
      "FEEDBACK": "${FEEDBACK}"
    },
    "commit_message": "Checkpoint: review iteration ${REVIEW_ITERATION}",
    "mr_title": "Implement: ${TASK}",
    "mr_description": "Approve or submit revision feedback.",
    "max_iterations": 5,
    "output_mapping": {
      "SUMMARY": "IMPLEMENTATION_SUMMARY"
    }
  },
  "position": { "x": 360, "y": 100 }
}
```

| Config field | Type | Required | Default / meaning |
|---|---|---:|---|
| `initial_workflow_id` | identifier | yes | Child used for iteration 1. |
| `revision_workflow_id` | identifier or `null` | no | Reuses initial child when omitted. |
| `inputs` | identifier-to-string object | no | `{}`; mappings for iteration 1. |
| `revision_inputs` | identifier-to-string object | no | `{}`; mappings for iterations 2+. |
| `commit_message` | string | no | `Checkpoint: review iteration ${REVIEW_ITERATION}` |
| `mr_title` | string or `null` | no | Workflow default when null. |
| `mr_description` | string or `null` | no | Workflow default when null. |
| `max_iterations` | positive integer or `null` | no | Workflow `max_review_iterations`. |
| `output_mapping` | identifier-to-identifier object | no | `{}`; latest child output to parent variable. |

Iteration 1 executes the initial child and pauses for review. Approval completes the
node. Comment feedback increments `REVIEW_ITERATION`, exposes `FEEDBACK`, executes the
revision child (or the initial child again), and pauses again.

Required authoring rules:

- Initial and revision child workflows must exist and the reference graph must not be
  recursive.
- Each directly referenced review child must not itself contain a `human_feedback` or
  `review_loop` node.
- Map all required inputs separately in `inputs` and `revision_inputs`.
- If `revision_workflow_id` is omitted, `revision_inputs` must still map every required
  input of the reused initial child.
- An `output_mapping` key must be declared by every child against which the validator
  checks the mapping. When initial and revision children differ, use shared output
  names.

## 7. Edges and conditions

An edge has this exact shape:

```json
{
  "id": "tests_to_publish",
  "source": "tests",
  "target": "publish",
  "condition": {
    "type": "exit_code",
    "operator": "equals",
    "value": 0
  }
}
```

`id`, `source`, and `target` are required identifiers. Edge IDs are unique within the
workflow. Source and target must name nodes in the same file. `condition` may be
omitted or `null`, which means the edge is true after a successful source node.

Conditions are discriminated by `type` and allow no extra fields.

### 7.1 Exit code

```json
{
  "type": "exit_code",
  "operator": "equals",
  "value": 0
}
```

`value` is an integer. `operator` is one of:

```text
equals
not_equals
greater_than
greater_than_or_equal
less_than
less_than_or_equal
```

### 7.2 Output contains

```json
{
  "type": "output_contains",
  "value": "SUCCESS",
  "stream": "stdout"
}
```

`value` is a string. `stream` is `stdout`, `stderr`, or `combined`, and defaults to
`stdout`.

### 7.3 File exists

```json
{
  "type": "file_exists",
  "value": "reports/summary.json"
}
```

`value` must be a non-empty relative repository path, must not contain a `..` path
component, and must resolve inside the worktree.

### 7.4 Public variable

```json
{
  "type": "variable",
  "name": "VALIDATION_RESULT",
  "operator": "equals",
  "value": "passed"
}
```

`name` is an identifier and must exist in public context when evaluated. `value` is a
template value. The current runtime converts both sides to strings before comparison,
so ordering operators are lexicographic here. Prefer `equals` and `not_equals`; use an
`exit_code` condition for numeric exit-code comparisons.

Conditions always observe the source node: its exit code, output, the worktree after
it finishes, and the public context available then.

## 8. Graph rules and join behavior

Every individual workflow graph must satisfy all of these rules:

- Node IDs are unique and edge IDs are unique.
- Every edge endpoint exists.
- At least one start node has no incoming edges.
- Every node is reachable from at least one start node.
- In a graph with multiple nodes, no node may be completely isolated.
- The graph has no directed cycle, including self-edges.
- Multiple start nodes and fan-out are allowed.

Ready Bash, Script, and Prompt nodes execute concurrently in a wave. Sub-workflow,
human-feedback, and review-loop nodes execute one at a time as control boundaries.

Join semantics are intentionally branch-merging semantics rather than boolean
all/any semantics:

- `join: "and"` waits for all incoming edges to be evaluated. It runs if at least one
  incoming edge is true and is skipped only if all are false.
- `join: "or"` runs as soon as the first incoming edge is true. If every predecessor
  becomes terminal and every incoming edge is false, it is skipped.

A skipped node's outgoing edges are currently evaluated false.

## 9. Settings

All settings are optional. These are the accepted fields and model defaults:

| Field | Type | Default | Constraint / use |
|---|---|---|---|
| `pi` | Pi settings object | `{}` | Workflow-wide provider, model, and skill defaults. |
| `auto_commit_after_wave` | boolean | `true` | Commit after every successful process wave. |
| `wave_commit_message_template` | string | `workflow(${WORKFLOW_ID}): wave ${WAVE_INDEX}` | Public template. |
| `final_commit_message_template` | string | `workflow(${WORKFLOW_ID}): complete run ${RUN_ID}` | Public template. |
| `mr_title_template` | string | `Workflow: ${WORKFLOW_NAME} (${RUN_ID_SHORT})` | Public template. |
| `mr_description_template` | string | See canonical object below. | Public template. |
| `timeout_per_node_seconds` | positive integer | `1800` | Capped by deployment configuration; default cap is 14400. |
| `max_review_iterations` | positive integer | `5` | Capped by deployment configuration; default cap is 10. |
| `max_subworkflow_depth` | positive integer | `8` | Accepted metadata; deployment cap is authoritative. |
| `max_output_variable_bytes` | integer >= 1024 | `65536` | Per-output public preview limit. |
| `propagate_skips` | boolean | `false` | Reserved; current runtime still makes skipped-source edges false. |

Canonical explicit settings object:

```json
{
  "pi": {
    "provider": "anthropic",
    "model": "anthropic/claude-sonnet-4-5",
    "skill": ".agents/skills/implementation/SKILL.md"
  },
  "auto_commit_after_wave": true,
  "wave_commit_message_template": "workflow(${WORKFLOW_ID}): wave ${WAVE_INDEX}",
  "final_commit_message_template": "workflow(${WORKFLOW_ID}): complete run ${RUN_ID}",
  "mr_title_template": "Workflow: ${WORKFLOW_NAME} (${RUN_ID_SHORT})",
  "mr_description_template": "Automated workflow run triggered by ${USER_NAME}.\n\nWorkflow: ${WORKFLOW_NAME}\nBase commit: ${BASE_COMMIT_SHA}\nRun: ${RUN_ID}",
  "timeout_per_node_seconds": 1800,
  "max_review_iterations": 5,
  "max_subworkflow_depth": 8,
  "max_output_variable_bytes": 65536,
  "propagate_skips": false
}
```

## 10. Cross-file composition rules

All workflows in one run are loaded from the exact same pinned Git commit. For a root
workflow, Kyron recursively loads every workflow referenced by `subworkflow` and
`review_loop` nodes from `.workflowEngine/<workflow_id>.json`.

The complete workflow-reference graph must be acyclic. Direct or indirect recursion
is invalid even when an edge condition would make the recursive node unreachable at
run time. The reference depth must not exceed the deployment's configured maximum,
which defaults to 8 and counts the root as depth 1.

## 11. Current implementation caveats

These fields are accepted by schema but do not yet alter current runtime behavior:

- `subworkflow.config.allow_failure`: a failed child currently fails its parent node.
- `human_feedback.config.allow_comment_feedback` and `allow_approval`: both feedback
  paths are currently accepted by the feedback service.
- `settings.propagate_skips`: skipped nodes currently persist false outgoing edges.
- `settings.max_subworkflow_depth`: the deployment-wide maximum is used for bundle
  validation.

An LLM should keep the first three behavior flags at their defaults and should not
promise behavior based on changing them.

Validation currently checks that `${...}` syntax is well formed only when the value is
expanded during execution. Therefore, an author must independently check every
template reference against inputs, variables, built-ins, earlier node outputs, mapped
child outputs, or feedback values available on that path.

## 12. LLM authoring procedure

Use this deterministic procedure:

1. Identify the root workflow and every child workflow required.
2. Assign all workflow, node, edge, input, output, and variable identifiers before
   writing JSON. Check each against the identifier regex.
3. Declare root trigger inputs and non-secret variables.
4. Define child workflow inputs and outputs before defining parent mappings.
5. Select project, workflow, and node Pi defaults; verify every configured skill path
   against the repository tree.
6. Add nodes with complete type-specific `config` objects.
7. Add only forward DAG edges. Use `review_loop` for repeated work.
8. For each `${NAME}`, prove that `NAME` exists before that field is expanded on every
   reachable path.
9. For each sub-workflow and review-loop node, check required child inputs and output
   mapping direction.
10. Check unique IDs, valid edge endpoints, reachability, absence of isolated nodes,
   graph acyclicity, and workflow-reference acyclicity.
11. Check timeouts and review limits against deployment caps.
12. Serialize each file as UTF-8 JSON with two-space indentation and a trailing
    newline.
13. Run server validation before saving or triggering.

## 13. Server validation API

The authoritative validation endpoint is:

```text
POST /projects/<project_uuid>/workflows/validate
```

Request body:

```json
{
  "workflow": { "id": "root_workflow", "version": 2 },
  "proposed_related_workflows": {
    "child_workflow": { "id": "child_workflow", "version": 2 }
  }
}
```

The abbreviated objects above illustrate the envelope only; each workflow must be a
complete root object. Put newly created or simultaneously changed child definitions in
`proposed_related_workflows`, keyed by their exact workflow IDs. Existing unchanged
children are resolved from the project's current default branch.

Success is `{"valid": true, "errors": [], "warnings": []}`. A `valid: false`
response contains stable `path`, `code`, and `message` fields. Schema validation,
bundle validation, and exact-commit run-time validation are authoritative.

Project-wide Pi defaults use this endpoint:

```text
PUT /projects/<project_uuid>/pi
```

The request body is the Pi settings object shown in section 3.1. Send `{}` to return
all fields to Pi's own defaults. Updating project defaults does not rewrite workflow
files; each new run snapshots the project values that apply when it is created.
