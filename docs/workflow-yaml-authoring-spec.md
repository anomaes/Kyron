# Kyron workflow YAML authoring specification

This document is the authoring contract for repository workflow files consumed by
the current Kyron implementation. It is intentionally written so that a person or
an LLM can create a workflow without reading backend source code.

The Pydantic models in `backend/schemas/workflow.py` and the validators in
`backend/engine/validation.py` remain authoritative if this document and the code
ever disagree. The broader product behavior is defined in
`workflow_orchestration_engine_spec.md`.

## 1. LLM output contract

When asked to create or change a workflow, produce one or more complete YAML files.
For every file:

1. Store it at `.workflowEngine/<optional folders>/<id>.yaml`.
2. Make the filename stem exactly equal to the root `id` value, including case.
3. Emit one YAML document with a top-level mapping. Do not use aliases, anchors,
   custom tags, duplicate mapping keys, or Markdown fences when raw file content
   is requested.
4. Set `version` to `2`.
5. Use only fields documented here. Unknown fields are validation errors at every
   level of the document.
6. Use a directed acyclic graph. Never model repetition with a back edge; use a
   `review_loop` node.
7. Include every transitively referenced child workflow as a separate file unless it
   already exists in the target repository.
8. Never put credentials, tokens, authenticated URLs, or other secrets in workflow
   YAML.

Prefer explicit fields and canonical defaults in generated files even where a field
may be omitted. This makes LLM output easier to review and less dependent on implicit
defaults.

## 2. Lexical types and naming

### 2.1 YAML document and scalar rules

Each file contains exactly one YAML document whose root value is a mapping. Use
spaces for indentation; tabs are not valid indentation. Mapping keys must be unique.
Aliases, anchors, custom tags, and merge keys are not part of the workflow language.

Write booleans as `true` or `false` and null values as `null`. Quote a value when it
must remain a string but resembles a number, boolean, or null value. Dates such as
`2026-07-29` remain strings.

Use literal block scalars for multiline text. Prefer `|-` when the string should not
end with a newline:

```yaml
prompt: |-
  Implement ${TASK}.

  Keep the change scoped and run the relevant tests.
```

Use `|` when a final newline is intentionally part of the value. Folded block scalars
such as `>-` are suitable for long prose that should become one logical line.

### 2.2 Identifier

Workflow IDs, node IDs, edge IDs, input names, output names, variable names, and
mapping names use this pattern:

```text
^[A-Za-z][A-Za-z0-9_]*$
```

They are 1 to 255 characters long, start with an ASCII letter, and contain only
ASCII letters, digits, and underscores. They are case-sensitive. Hyphens, spaces,
dots, and leading underscores are invalid.

Examples: `implement_review`, `RunTests2`, `TASK`, `NODE_RESULT`.

### 2.3 Template value

A template value is a YAML string, integer, number, or boolean. It is never a sequence,
mapping, or `null`, except that an input's `default` may explicitly be `null`.

### 2.4 Tag

A tag is 1 to 64 characters and matches:

```text
^[a-z0-9][a-z0-9._-]*$
```

Tags must be unique within a workflow. A workflow may contain at most 32 tags. Tags
are catalog metadata and do not change execution.

Workflow files may be nested to any depth below `.workflowEngine/`; for example,
`.workflowEngine/teams/platform/deploy.yaml`. The catalog mirrors these folders. Folder
names are not added to `tags`, and references continue to use only the workflow ID. IDs
must therefore be unique across all folders. The top-level `templates/` folder is reserved
for node templates.

## 3. Root workflow mapping

The root mapping has this shape. Fields marked required must be present.

| Field | Type | Required | Default / constraint |
|---|---|---:|---|
| `id` | identifier | yes | Must equal the filename stem. |
| `name` | string | yes | 1 to 255 characters. |
| `description` | string | no | `""` |
| `version` | integer | no | Must be exactly `2`; write it explicitly. |
| `created_by` | string | yes | Conventionally an email address; no format validation. |
| `tags` | tag sequence | no | `[]`; unique; at most 32. |
| `inputs` | mapping | no | `{}`; keys are identifiers. |
| `outputs` | mapping | no | `{}`; keys are identifiers. |
| `variables` | mapping | no | `{}`; identifier keys and template values. |
| `nodes` | node sequence | yes | Must contain at least one node after semantic validation. |
| `edges` | edge sequence | no | `[]` |
| `settings` | settings mapping | no | `{}` applies project and engine defaults. |

Minimal valid workflow:

```yaml
id: hello_world
name: Hello world
description: A minimal Kyron workflow.
version: 2
created_by: automation@example.com
tags:
  - example
inputs: {}
outputs: {}
variables: {}
nodes:
  - id: hello
    type: bash
    label: Print greeting
    join: and
    config:
      command: echo 'Hello from Kyron'
      allow_failure: false
      shell: /bin/bash
    position:
      x: 100
      y: 100
edges: []
settings: {}
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

```yaml
provider: anthropic
model: anthropic/claude-sonnet-4-5
skill: .agents/skills/implementation/SKILL.md
```

All fields are optional. `provider` and `model` are passed to Pi as `--provider` and
`--model`. Both must name something Pi knows: a built-in provider, or one the operator
registered through `PI_MODELS_CONFIG_PATH`. `skill` names a Markdown skill manifest or skill directory relative to the
repository root. A directory must contain `SKILL.md`. The resolved file must remain
inside the run worktree. Kyron loads that one skill explicitly and invokes its
`/skill:<name>` command. This works with Pi's project trust disabled and ties the skill
contents to the run's exact base commit.

The manifest's YAML frontmatter must declare a non-empty `description`, which is what
Pi requires to load a skill at all. `name` is optional and defaults to the name of the
directory containing `SKILL.md`; when present it must be a valid Pi command name
(lowercase letters, digits, and single interior hyphens, at most 64 characters).

```yaml
---
name: implementation
description: Implement a scoped change and run the relevant tests.
---
```

A skill that Pi cannot load is skipped rather than applied silently: the run log
records a `PI_SKILL_SKIPPED` warning naming the skill and the reason, and the node runs
the prompt without the skill and without its `/skill:<name>` prefix. This covers a skill
path that is missing at the run's pinned commit, a manifest with no frontmatter, a
missing or empty `description`, and a `name` Pi could not expose as a command. A skill
path that escapes the run worktree fails the node before Pi starts.

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

```yaml
inputs:
  TASK:
    type: string
    required: true
    description: The change to implement
  RETRIES:
    type: integer
    required: false
    default: 2
```

Root trigger inputs are type-checked. Booleans are not accepted as integers or
numbers. Unknown trigger input names are rejected. If `required` is true and
`default` is `null` or absent, the caller must supply the input.

Always make the YAML scalar type of a non-null default agree with the declared `type`.

### 4.2 Variables

`variables` defines non-secret public context defaults:

```yaml
variables:
  TARGET_DIR: src/
  STRICT: true
  RETRY_COUNT: 2
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

Kyron also copies the complete public context into the environment of every Bash,
Script, and Prompt process. Bash can read `$TASK`; a Python script can read
`os.environ["TASK"]`; and Script `args` can use `${TASK}`. Prompt text must use
`${TASK}` when the value should be inserted into the prompt. Prompt nodes are not
launched through a shell, so `$TASK` in prompt text remains literal.

Secrets are injected only into subprocess environments. Every Bash, Script, and Prompt
process receives all credentials owned by the user who triggered the run. In a Bash
command use the shell's native `$SECRET_NAME` form for a credential.
`${SECRET_NAME}` asks Kyron for a public variable and fails if only a secret exists.
Script and prompt templates cannot expand secrets.

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
| `WORKSPACE_ID` | Isolated workspace UUID; empty in a shared child. |
| `WORKSPACE_BRANCH` | Isolated child branch; empty in a shared child. |
| `WORKSPACE_BASE_COMMIT_SHA` | Exact parent checkpoint from which an isolated workspace forked. |
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

These values become available only after the producing wave completes. A downstream
node connected through the graph can use `${NODE_choose_STDOUT}` in a supported template
or `$NODE_choose_STDOUT` from its process environment. Siblings running concurrently in
the same wave cannot consume one another's outputs. Shell `export` statements do not
persist into later nodes because every node starts in a new subprocess.

### 4.5 Declared outputs

Each `outputs` entry has this shape:

| Field | Type | Required | Default / constraint |
|---|---|---:|---|
| `type` | `string`, `integer`, `number`, or `boolean` | no | `string` |
| `source` | string | yes | Public template expanded at invocation completion. |
| `description` | string or `null` | no | `null` |

Example:

```yaml
outputs:
  TEST_EXIT_CODE:
    type: string
    source: ${NODE_tests_EXIT_CODE}
    description: Exit code rendered as text
```

The current runtime expands every output source to a string and does not enforce the
declared output type. Declare generated outputs as `string` unless a consumer uses the
type only as catalog metadata.

## 5. Common node mapping

Every node is one of the six discriminated node types below and contains:

| Field | Type | Required | Default / constraint |
|---|---|---:|---|
| `id` | identifier | yes | Unique within the workflow. |
| `type` | node-type literal | yes | Selects the exact `config` schema. |
| `label` | string | yes | 1 to 255 characters. |
| `join` | `and` or `or` | no | `and` |
| `config` | mapping | yes | Exact shape depends on `type`. |
| `position` | mapping with `x` and `y` numbers | no | Both coordinates default to `0`. |

`position` affects only builder layout. `join` affects only nodes with incoming edges.

## 6. Node types

### 6.1 Bash

```yaml
id: tests
type: bash
label: Run tests
join: and
config:
  command: python -m pytest ${TEST_ARGS}
  timeout: 1800
  allow_failure: false
  shell: /bin/bash
position:
  x: 360
  y: 100
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

```yaml
id: validate
type: script
label: Validate result
join: and
config:
  script: scripts/validate.py
  python: python3
  args:
    - --target
    - ${TARGET_DIR}
  timeout: 900
  allow_failure: false
position:
  x: 620
  y: 100
```

| Config field | Type | Required | Default / constraint |
|---|---|---:|---|
| `script` | non-empty string | yes | Relative repository path; no `..`; must exist at run time. |
| `python` | string | no | `python3` |
| `args` | string sequence | no | `[]`; public templates expand per item. |
| `timeout` | positive integer or `null` | no | Workflow default timeout. |
| `allow_failure` | boolean | no | `false` |

The process runs without a shell as `[python, absolute_script_path, ...args]` in the
worktree.

### 6.3 Prompt

```yaml
id: implement
type: prompt
label: Implement task
join: and
config:
  prompt: |-
    Implement this task: ${TASK}

    Inspect the repository first, keep the change scoped, and run relevant tests.
  provider: anthropic
  model: anthropic/claude-sonnet-4-5
  skill: .agents/skills/implementation/SKILL.md
  timeout: 1800
  allow_failure: false
  project_trust: never
position:
  x: 360
  y: 100
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
resolves to a value, the path should exist at the run's pinned commit and declare a
`description` in its frontmatter; a missing or malformed skill is recorded as a
`PI_SKILL_SKIPPED` warning on the run log and skipped, and the node runs the prompt
without it. A skill path that escapes the run worktree fails the node before Pi starts.

Do not invent provider, model, or skill values. Use values supplied by the user or
already used by the repository; otherwise omit them.

### 6.4 Human feedback

```yaml
id: review
type: human_feedback
label: Await review
join: and
config:
  approval_policy: default
  commit_message: 'Checkpoint: awaiting review'
  mr_title: Review ${WORKFLOW_NAME}
  mr_description: Approve to continue or submit feedback.
  allow_comment_feedback: true
  allow_approval: true
position:
  x: 620
  y: 100
```

| Config field | Type | Required | Default |
|---|---|---:|---|
| `approval_policy` | project policy key | no | `default` |
| `commit_message` | string | no | `Checkpoint: awaiting review` |
| `mr_title` | string or `null` | no | Workflow MR title template. |
| `mr_description` | string or `null` | no | Workflow MR description template. |
| `allow_comment_feedback` | boolean | no | `true` |
| `allow_approval` | boolean | no | `true` |

This node checkpoints, pushes, opens or updates the provider change request, and pauses.
Eligible reviewers are resolved from the selected policy. Approvals continue only after every
requirement reaches quorum; eligible feedback completes this standalone node. It does not repeat
prior nodes, so use `review_loop` for revision cycles.

Every project has a `default` approval policy. Its only eligible approver is the user who
triggered the workflow, and its single requirement has quorum 1. Omit `approval_policy` or use
`approval_policy: default` for that behavior. Replace the key with a project-specific policy
when the workflow later needs independent reviewers or a larger quorum.

### 6.5 Sub-workflow

```yaml
id: run_child
type: subworkflow
label: Run validation workflow
join: and
config:
  workflow_id: validate_change
  execution_mode: shared
  inputs:
    TARGET_DIR: ${TARGET_DIR}
  output_mapping:
    RESULT: VALIDATION_RESULT
  allow_failure: false
position:
  x: 620
  y: 100
```

| Config field | Type | Required | Default / meaning |
|---|---|---:|---|
| `workflow_id` | identifier | yes | Child workflow file ID. |
| `execution_mode` | `shared`, `isolated`, or `isolated_parallel` | no | `shared` |
| `inputs` | identifier-to-string mapping | no | `{}`; child input name to parent template. |
| `output_mapping` | identifier-to-identifier mapping | no | `{}`; child output name to new parent public-variable name. |
| `allow_failure` | boolean | no | `false` |

Mapping direction is important:

```text
inputs:         CHILD_INPUT  -> "parent template"
output_mapping: CHILD_OUTPUT -> PARENT_VARIABLE
```

Every required child input without a non-null default must be present in `inputs`.
Every output-mapping key must be declared by the child workflow.

Execution modes define the child's Git and scheduling boundary:

- `shared` executes serially in the parent workspace and branch. This is the
  backward-compatible default and has no additional worktree overhead.
- `isolated` forks a child branch and worktree from the parent's exact clean
  checkpoint, executes the child serially, and merges the successful child head
  into the parent.
- `isolated_parallel` uses the same Git isolation and may execute concurrently
  with ready sibling nodes in that mode. The parent workspace remains frozen
  until the complete batch is ready to integrate.

Ready parallel siblings receive inputs expanded from the same frozen parent context.
They cannot observe each other's process outputs. Their successful heads are merged
into the parent in ascending parent node-ID order. Integration is atomic: a conflict
restores the parent to the batch's exact starting commit, publishes no mapped output,
and fails the batch.

Independent `isolated_parallel` nodes must map outputs to distinct parent variables.
Kyron rejects a workflow when unordered parallel children both target the same parent
variable. Place a graph edge between children when one must run after the other.

An isolated child that reaches a human checkpoint uses a workspace review request
whose source is the child branch and whose target is the immediate parent workspace
branch. Later checkpoints in that child reuse the same review request and require a
fresh gate decision. The root run's final change request remains separate and targets
`base_ref`.

### 6.6 Review loop

```yaml
id: implementation_review
type: review_loop
label: Implement and review
join: and
config:
  approval_policy: default
  initial_workflow_id: implement_change
  revision_workflow_id: revise_change
  inputs:
    TASK: ${TASK}
  revision_inputs:
    TASK: ${TASK}
    FEEDBACK: ${FEEDBACK}
  commit_message: 'Checkpoint: review iteration ${REVIEW_ITERATION}'
  mr_title: 'Implement: ${TASK}'
  mr_description: Approve or submit revision feedback.
  max_iterations: 5
  output_mapping:
    SUMMARY: IMPLEMENTATION_SUMMARY
position:
  x: 360
  y: 100
```

| Config field | Type | Required | Default / meaning |
|---|---|---:|---|
| `approval_policy` | project policy key | no | `default`; only the workflow triggerer, quorum 1. |
| `initial_workflow_id` | identifier | yes | Child used for iteration 1. |
| `revision_workflow_id` | identifier or `null` | no | Reuses initial child when omitted. |
| `inputs` | identifier-to-string mapping | no | `{}`; mappings for iteration 1. |
| `revision_inputs` | identifier-to-string mapping | no | `{}`; mappings for iterations 2+. |
| `commit_message` | string | no | `Checkpoint: review iteration ${REVIEW_ITERATION}` |
| `mr_title` | string or `null` | no | Workflow default when null. |
| `mr_description` | string or `null` | no | Workflow default when null. |
| `max_iterations` | positive integer or `null` | no | Workflow `max_review_iterations`. |
| `output_mapping` | identifier-to-identifier mapping | no | `{}`; latest child output to parent variable. |

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

```yaml
id: tests_to_publish
source: tests
target: publish
condition:
  type: exit_code
  operator: equals
  value: 0
```

`id`, `source`, and `target` are required identifiers. Edge IDs are unique within the
workflow. Source and target must name nodes in the same file. `condition` may be
omitted or `null`, which means the edge is true after a successful source node.

Conditions are discriminated by `type` and allow no extra fields.

### 7.1 Exit code

```yaml
type: exit_code
operator: equals
value: 0
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

```yaml
type: output_contains
value: SUCCESS
stream: stdout
```

`value` is a string. `stream` is `stdout`, `stderr`, or `combined`, and defaults to
`stdout`.

### 7.3 File exists

```yaml
type: file_exists
value: reports/summary.json
```

`value` must be a non-empty relative repository path, must not contain a `..` path
component, and must resolve inside the worktree.

### 7.4 Public variable

```yaml
type: variable
name: VALIDATION_RESULT
operator: equals
value: passed
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

Ready Bash, Script, and Prompt nodes execute concurrently in a wave. Shared and
isolated-serial sub-workflows, human-feedback nodes, and review-loop nodes execute one
at a time as control boundaries. When the lowest ready control is an
`isolated_parallel` sub-workflow, every ready sibling in that mode forms one isolated
batch.
Process output variables are published after the wave completes, so data dependencies
between process nodes must be represented by graph edges rather than parallel siblings.

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
| `pi` | Pi settings mapping | `{}` | Workflow-wide provider, model, and skill defaults. |
| `delivery_mode` | `propose_changes` or `report_only` | `propose_changes` | Controls whether Git changes are delivered or the pinned subject is only examined. |
| `credential_access` | credential policy mapping | `{mode: default, keys: []}` | Resolves to all credentials for delivery workflows and no credentials for report-only workflows. |
| `verification_publication` | verification publication mapping | all fields `true` | Controls commit status and subject change-request summary publication. |
| `auto_commit_after_wave` | boolean | `true` | Commit after every successful process wave. |
| `wave_commit_message_template` | string | `workflow(${WORKFLOW_ID}): wave ${WAVE_INDEX}` | Public template. |
| `final_commit_message_template` | string | `workflow(${WORKFLOW_ID}): complete run ${RUN_ID}` | Public template. |
| `mr_title_template` | string | `Workflow: ${WORKFLOW_NAME} (${RUN_ID_SHORT})` | Public template. |
| `mr_description_template` | string | See canonical mapping below. | Public template. |
| `timeout_per_node_seconds` | positive integer | `1800` | Capped by deployment configuration; default cap is 14400. |
| `max_review_iterations` | positive integer | `5` | Capped by deployment configuration; default cap is 10. |
| `max_subworkflow_depth` | positive integer | `8` | Accepted metadata; deployment cap is authoritative. |
| `max_output_variable_bytes` | integer >= 1024 | `65536` | Per-output public preview limit. |
| `propagate_skips` | boolean | `false` | Reserved; current runtime still makes skipped-source edges false. |

Canonical explicit settings mapping:

```yaml
pi:
  provider: anthropic
  model: anthropic/claude-sonnet-4-5
  skill: .agents/skills/implementation/SKILL.md
delivery_mode: propose_changes
credential_access:
  mode: default
  keys: []
verification_publication:
  publish_commit_status: true
  post_change_request_summary: true
  publication_required: true
auto_commit_after_wave: true
wave_commit_message_template: 'workflow(${WORKFLOW_ID}): wave ${WAVE_INDEX}'
final_commit_message_template: 'workflow(${WORKFLOW_ID}): complete run ${RUN_ID}'
mr_title_template: 'Workflow: ${WORKFLOW_NAME} (${RUN_ID_SHORT})'
mr_description_template: |-
  Automated workflow run triggered by ${USER_NAME}.

  Workflow: ${WORKFLOW_NAME}
  Base commit: ${BASE_COMMIT_SHA}
  Run: ${RUN_ID}
timeout_per_node_seconds: 1800
max_review_iterations: 5
max_subworkflow_depth: 8
max_output_variable_bytes: 65536
propagate_skips: false
```

`credential_access.mode` is `default`, `none`, `all`, or `allowlist`.
`allowlist` requires a non-empty, duplicate-free `keys` sequence; every other mode
requires an empty sequence. The resolved `default` is `all` for `propose_changes`
and `none` for `report_only`.

A report-only root examines the selected branch or change-request source commit
in disposable worktrees. It may create local commits as checkpoints, but it does
not push a result branch or create a change request. Its workflow bundle comes
from the trusted project default branch (or an authorized local definition
snapshot), independently of the code commit under examination. Human-feedback
and review-loop nodes are invalid anywhere in its transitive workflow bundle.
Isolated sub-workflows remain local and retain the same integration semantics.

## 10. Cross-file composition rules

All workflows in one run are loaded from the exact same pinned definition commit.
For ordinary delivery runs this is normally the code subject commit. For report-only
runs it is the trusted project default-branch commit, while the root worktree starts
at the separately pinned subject commit. For a root
workflow, Kyron recursively loads every workflow referenced by `subworkflow` and
`review_loop` nodes from the file indexed for that workflow ID anywhere below
`.workflowEngine/`.

The complete workflow-reference graph must be acyclic. Direct or indirect recursion
is invalid even when an edge condition would make the recursive node unreachable at
run time. The reference depth must not exceed the deployment's configured maximum,
which defaults to 8 and counts the root as depth 1.

## 11. Current implementation caveats

These fields are accepted by schema but do not yet alter current runtime behavior:

- `subworkflow.config.allow_failure` applies to isolated batches; a failed shared
  child still fails its parent node.
- `settings.propagate_skips`: skipped nodes currently persist false outgoing edges.
- `settings.max_subworkflow_depth`: the deployment-wide maximum is used for bundle
  validation.

An LLM should keep reserved behavior flags at their defaults and should not promise
behavior based on changing them.

Validation currently checks that `${...}` syntax is well formed only when the value is
expanded during execution. Therefore, an author must independently check every
template reference against inputs, variables, built-ins, earlier node outputs, mapped
child outputs, or feedback values available on that path.

## 12. LLM authoring procedure

Use this deterministic procedure:

1. Identify the root workflow and every child workflow required.
2. Assign all workflow, node, edge, input, output, and variable identifiers before
   writing YAML. Check each against the identifier regex.
3. Select the delivery and credential policies, then declare root trigger inputs
   and non-secret variables.
4. Define child workflow inputs and outputs before defining parent mappings.
5. Select project, workflow, and node Pi defaults; verify every configured skill path
   against the repository tree and confirm each manifest declares a `description`.
6. Add nodes with complete type-specific `config` mappings.
7. Add only forward DAG edges. Use `review_loop` for repeated work.
8. For each `${NAME}`, prove that `NAME` exists before that field is expanded on every
   reachable path.
9. For each sub-workflow and review-loop node, check required child inputs and output
   mapping direction.
10. Check unique IDs, valid edge endpoints, reachability, absence of isolated nodes,
   graph acyclicity, and workflow-reference acyclicity.
11. Check timeouts and review limits against deployment caps.
12. Serialize each file as UTF-8 YAML with two-space indentation and a trailing
    newline. Use literal block scalars for multiline prompts, commands, and descriptions.
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
