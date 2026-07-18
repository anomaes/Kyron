---
title: Example library
description: Copyable patterns for common Kyron workflow designs.
---

# Example library

These patterns are deliberately small. Adapt commands, timeouts, model settings, and paths to the repository before using them.

## Parallel quality checks

With no edge between `tests` and `lint`, both nodes are ready together and execute in one wave. `review` uses an AND join and waits for both.

```json
{
  "id": "quality_gate",
  "name": "Quality gate",
  "version": 2,
  "created_by": "platform@example.com",
  "tags": ["quality"],
  "inputs": {},
  "outputs": {},
  "variables": {},
  "nodes": [
    {
      "id": "tests",
      "type": "bash",
      "label": "Run tests",
      "config": { "command": "pytest -q", "allow_failure": false, "shell": "/bin/bash" }
    },
    {
      "id": "lint",
      "type": "bash",
      "label": "Run lint",
      "config": { "command": "ruff check .", "allow_failure": false, "shell": "/bin/bash" }
    },
    {
      "id": "review",
      "type": "human_feedback",
      "label": "Review quality result",
      "join": "and",
      "config": {
        "commit_message": "Checkpoint: quality gate complete",
        "allow_comment_feedback": true,
        "allow_approval": true
      }
    }
  ],
  "edges": [
    { "id": "tests_to_review", "source": "tests", "target": "review" },
    { "id": "lint_to_review", "source": "lint", "target": "review" }
  ],
  "settings": {}
}
```

If lint fails, test changes are rolled back too and both receive fresh attempts on resume.

## Conditional packaging

Package only when the build emits a known artifact:

```json
{
  "id": "build_to_package",
  "source": "build",
  "target": "package",
  "condition": {
    "type": "file_exists",
    "value": "dist/application.tar.gz"
  }
}
```

Keep artifact paths repository-relative. For files that belong outside Git, write them under `${RUN_DATA_PATH}` and use process output or a public variable for routing instead.

## Script with argument templates

```json
{
  "id": "release_notes",
  "type": "script",
  "label": "Generate release notes",
  "config": {
    "script": "tools/release_notes.py",
    "python": "python3",
    "args": ["--base", "${BASE_COMMIT_SHA}", "--output", "${RUN_DATA_PATH}/notes.md"],
    "timeout": 300,
    "allow_failure": false
  }
}
```

Each `args` entry expands independently and is passed in an argument array.

## Reusable verification child

Parent node:

```json
{
  "id": "verify",
  "type": "subworkflow",
  "label": "Verify implementation",
  "config": {
    "workflow_id": "repository_verification",
    "inputs": {
      "MODE": "strict"
    },
    "output_mapping": {
      "VERIFICATION_SUMMARY": "SUMMARY"
    },
    "allow_failure": false
  }
}
```

The child definition must declare a `MODE` input and `SUMMARY` output at the run's exact base commit.

## Implementation and revision children

Keep the prompt contract in the child workflow instead of embedding it in the loop node.

Initial prompt:

```json
"prompt": "Implement ${TASK}. Inspect the repository first, keep changes scoped, and run relevant tests."
```

Revision prompt:

```json
"prompt": "Revise the current implementation for this task: ${ORIGINAL_TASK}\n\nReviewer feedback: ${REVIEW_FEEDBACK}\n\nMake the smallest complete correction and rerun relevant tests."
```

Then map `TASK` into the initial child and `ORIGINAL_TASK` plus `${FEEDBACK}` into the revision child as shown in [review loops](/workflows/review-loops).

## Authoring checklist

Before merging any example-derived workflow:

- [ ] The filename stem equals the root workflow ID.
- [ ] Every command and script path is valid in the target repository.
- [ ] No token, credential, or authenticated URL appears in JSON.
- [ ] All child definitions exist at the same commit.
- [ ] Both satisfied and unsatisfied condition paths were tested.
- [ ] Review loops have a small bound and explicit revision inputs.
- [ ] Required provider permissions were verified.
- [ ] Failure and resume behavior is acceptable at each parallel wave.

For every field and constraint, use the [complete authoring specification](/workflow-json-authoring-spec).
