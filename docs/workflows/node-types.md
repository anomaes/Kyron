---
title: Node types
description: Configuration and behavior for every Kyron workflow node.
---

# Node types

Every node contains an identifier, type, label, join mode, type-specific configuration, and optional canvas position.

```yaml
id: unique_node_id
type: bash
label: Human-readable label
join: and
config: {}
position:
  x: 100
  y: 100
```

## Bash

Runs an inline command in the run worktree.

```yaml
id: tests
type: bash
label: Run unit tests
config:
  command: pytest -q
  timeout: 1200
  allow_failure: false
  shell: /bin/bash
```

`command` supports public templates. `timeout` must be positive and cannot exceed the server maximum. Credentials are injected into the environment, so access them with native shell syntax.

Use Bash for short, legible commands. Move complex logic into a reviewed repository script.

## Script

Executes a repository-local Python script using an argument array.

```yaml
id: analyze
type: script
label: Analyze changed files
config:
  script: tools/analyze_changes.py
  python: python3
  args:
    - --run
    - ${RUN_ID}
    - --strict
  timeout: 600
  allow_failure: false
```

The script path must be relative and stay inside the repository; absolute paths and `..` components are rejected. Templates expand in individual `args`, not in `script` or `python`. Kyron invokes the interpreter with an argument array rather than a constructed shell string.

## Prompt

Runs the Pi coding agent non-interactively in the worktree. Pi and its child processes
may write only to that run worktree and an ephemeral state directory; the rest of the
container filesystem is read-only. Filesystem reads, model-provider network access, and
the injected environment remain available.

Prompt processes see an empty read-only `/proc`, so tools such as `ps` and commands that
depend on procfs information are not available through Pi's Bash tool.

```yaml
id: implement
type: prompt
label: Implement request
config:
  prompt: |-
    Implement the following task:

    ${TASK}

    Keep the change scoped and run relevant tests.
  provider: null
  model: null
  skill: null
  timeout: 3600
  allow_failure: false
  project_trust: never
```

`prompt` supports public templates. `provider`, `model`, and `skill` are passed as
configuration, not template-expanded fields. Each omitted value inherits from the
workflow and then the project. A skill is a repository-relative Markdown manifest or
directory containing `SKILL.md`; Kyron loads the exact file from the pinned worktree
and explicitly invokes the skill. The manifest must declare a `description` in its
frontmatter; `name` is optional and defaults to the containing directory's name. A
skill that cannot be loaded is recorded as a `PI_SKILL_SKIPPED` warning on the run log
and skipped, and the prompt runs without it. `project_trust` remains fixed to `never`.

Prompt stdout contains Pi's raw JSONL event stream. Kyron also parses events into readable live logs and uses the terminal result event to determine success.

## Human feedback

Creates or updates the run change request and pauses for the selected approval policy.

```yaml
id: approval
type: human_feedback
label: Approve implementation
config:
  approval_policy: default
  commit_message: 'Checkpoint: awaiting implementation review'
  mr_title: Review ${WORKFLOW_NAME}
  mr_description: Run ${RUN_ID} is ready for review.
  allow_comment_feedback: true
  allow_approval: true
```

At least one feedback mode should be useful to the workflow. Continue with [reviews and feedback](/guides/review-and-feedback) for provider and identity semantics.

## Sub-workflow

Invokes one child workflow from the run's immutable bundle.

```yaml
id: quality
type: subworkflow
label: Run quality checks
config:
  workflow_id: quality_checks
  execution_mode: shared
  inputs:
    STRICT: ${STRICT}
  output_mapping:
    RESULT: QUALITY_RESULT
  allow_failure: false
```

Input mapping keys identify child inputs and their values are parent expressions. Output mapping
keys identify child outputs and their values are the new public names in the parent. Definitions
are resolved from the same base commit. `shared` executes in the parent workspace;
`isolated` uses a child branch and worktree; `isolated_parallel` also batches ready
siblings for concurrent execution. See [composition](/workflows/composition).

## Review loop

Runs an initial child, pauses for review, and optionally invokes a revision child after comment feedback.

```yaml
id: implementation_loop
type: review_loop
label: Implement until approved
config:
  approval_policy: default
  initial_workflow_id: implement_change
  revision_workflow_id: revise_change
  inputs:
    TASK: ${TASK}
  revision_inputs:
    TASK: ${TASK}
    REVIEW_FEEDBACK: ${FEEDBACK}
  commit_message: 'Checkpoint: review iteration ${REVIEW_ITERATION}'
  max_iterations: 4
  output_mapping: {}
```

Use this node instead of a graph back edge. Read [review loops](/workflows/review-loops) before relying on its iteration and output semantics.

## Process nodes versus control nodes

| Category | Nodes | Scheduling |
| --- | --- | --- |
| Process | Bash, Script, Prompt | Ready siblings may execute together in a wave |
| Control | Human feedback, Sub-workflow, Review loop | Serialized, except ready `isolated_parallel` sub-workflows form one isolated batch |

This distinction explains why adding a control node changes the execution boundaries even when the graph looks parallel.
