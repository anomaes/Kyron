---
title: Node types
description: Configuration and behavior for every Kyron workflow node.
---

# Node types

Every node contains an identifier, type, label, join mode, type-specific configuration, and optional canvas position.

```json
{
  "id": "unique_node_id",
  "type": "bash",
  "label": "Human-readable label",
  "join": "and",
  "config": {},
  "position": { "x": 100, "y": 100 }
}
```

## Bash

Runs an inline command in the run worktree.

```json
{
  "id": "tests",
  "type": "bash",
  "label": "Run unit tests",
  "config": {
    "command": "pytest -q",
    "timeout": 1200,
    "allow_failure": false,
    "shell": "/bin/bash"
  }
}
```

`command` supports public templates. `timeout` must be positive and cannot exceed the server maximum. Credentials are injected into the environment, so access them with native shell syntax.

Use Bash for short, legible commands. Move complex logic into a reviewed repository script.

## Script

Executes a repository-local Python script using an argument array.

```json
{
  "id": "analyze",
  "type": "script",
  "label": "Analyze changed files",
  "config": {
    "script": "tools/analyze_changes.py",
    "python": "python3",
    "args": ["--run", "${RUN_ID}", "--strict"],
    "timeout": 600,
    "allow_failure": false
  }
}
```

The script path must be relative and stay inside the repository; absolute paths and `..` components are rejected. Templates expand in individual `args`, not in `script` or `python`. Kyron invokes the interpreter with an argument array rather than a constructed shell string.

## Prompt

Runs the Pi coding agent non-interactively in the worktree.

```json
{
  "id": "implement",
  "type": "prompt",
  "label": "Implement request",
  "config": {
    "prompt": "Implement ${TASK}. Keep the change scoped and run relevant tests.",
    "provider": null,
    "model": null,
    "skill": null,
    "timeout": 3600,
    "allow_failure": false,
    "project_trust": "never"
  }
}
```

`prompt` supports public templates. `provider`, `model`, and `skill` are passed as
configuration, not template-expanded fields. Each omitted value inherits from the
workflow and then the project. A skill is a repository-relative Markdown manifest or
directory containing `SKILL.md`; Kyron loads the exact file from the pinned worktree
and explicitly invokes the skill. `project_trust` remains fixed to `never`.

Prompt stdout contains Pi's raw JSONL event stream. Kyron also parses events into readable live logs and uses the terminal result event to determine success.

## Human feedback

Creates or updates the run change request and pauses for the selected approval policy.

```json
{
  "id": "approval",
  "type": "human_feedback",
  "label": "Approve implementation",
  "config": {
    "approval_policy": "production-review",
    "commit_message": "Checkpoint: awaiting implementation review",
    "mr_title": "Review ${WORKFLOW_NAME}",
    "mr_description": "Run ${RUN_ID} is ready for review.",
    "allow_comment_feedback": true,
    "allow_approval": true
  }
}
```

At least one feedback mode should be useful to the workflow. Continue with [reviews and feedback](/guides/review-and-feedback) for provider and identity semantics.

## Sub-workflow

Invokes one child workflow from the run's immutable bundle.

```json
{
  "id": "quality",
  "type": "subworkflow",
  "label": "Run quality checks",
  "config": {
    "workflow_id": "quality_checks",
    "inputs": {
      "STRICT": "${STRICT}"
    },
    "output_mapping": {
      "RESULT": "QUALITY_RESULT"
    },
    "allow_failure": false
  }
}
```

Input mapping keys identify child inputs and their values are parent expressions. Output mapping
keys identify child outputs and their values are the new public names in the parent. Definitions
are resolved from the same base commit. See [composition](/workflows/composition).

## Review loop

Runs an initial child, pauses for review, and optionally invokes a revision child after comment feedback.

```json
{
  "id": "implementation_loop",
  "type": "review_loop",
  "label": "Implement until approved",
  "config": {
    "approval_policy": "production-review",
    "initial_workflow_id": "implement_change",
    "revision_workflow_id": "revise_change",
    "inputs": {
      "TASK": "${TASK}"
    },
    "revision_inputs": {
      "TASK": "${TASK}",
      "REVIEW_FEEDBACK": "${FEEDBACK}"
    },
    "commit_message": "Checkpoint: review iteration ${REVIEW_ITERATION}",
    "max_iterations": 4,
    "output_mapping": {}
  }
}
```

Use this node instead of a graph back edge. Read [review loops](/workflows/review-loops) before relying on its iteration and output semantics.

## Process nodes versus control nodes

| Category | Nodes | Scheduling |
| --- | --- | --- |
| Process | Bash, Script, Prompt | Ready siblings may execute together in a wave |
| Control | Human feedback, Sub-workflow, Review loop | Serialized so durable orchestration transitions remain unambiguous |

This distinction explains why adding a control node changes the execution boundaries even when the graph looks parallel.
