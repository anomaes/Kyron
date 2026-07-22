---
title: Composition
description: Reuse workflows safely with child invocations, mappings, and immutable bundles.
---

# Composition

Sub-workflows let you package a reusable graph—quality checks, repository analysis, implementation, or release preparation—and invoke it from multiple parents.

## Define a child

Create `.workflowEngine/quality_checks.json`:

```json
{
  "id": "quality_checks",
  "name": "Quality checks",
  "description": "Run repository tests and expose the result.",
  "version": 2,
  "created_by": "platform@example.com",
  "tags": ["quality", "reusable"],
  "inputs": {
    "COMMAND": {
      "type": "string",
      "required": true
    }
  },
  "outputs": {
    "RESULT": {
      "type": "string",
      "source": "${NODE_tests_EXIT_CODE}"
    }
  },
  "variables": {},
  "nodes": [
    {
      "id": "tests",
      "type": "bash",
      "label": "Run checks",
      "config": {
        "command": "${COMMAND}",
        "allow_failure": false,
        "shell": "/bin/bash"
      }
    }
  ],
  "edges": [],
  "settings": {}
}
```

## Invoke it from a parent

```json
{
  "id": "quality",
  "type": "subworkflow",
  "label": "Verify repository",
  "config": {
    "workflow_id": "quality_checks",
    "inputs": {
      "COMMAND": "${TEST_COMMAND}"
    },
    "output_mapping": {
      "RESULT": "QUALITY_EXIT_CODE"
    },
    "allow_failure": false
  }
}
```

The `inputs` object maps **child input name → parent template expression**. The `output_mapping` object maps **child output name → new parent variable name**.

After the child completes, this example makes `${QUALITY_EXIT_CODE}` available to later nodes in the parent invocation.

## Exact-revision guarantee

At trigger time, Kyron indexes workflow files at the exact base commit, then recursively
follows every `subworkflow` and `review_loop` reference from the root. Definitions may live
in nested `.workflowEngine/` folders; IDs remain globally unique and the resolved files are
stored in one secret-free bundle.

The consequences are important:

- a child cannot drift to a newer default-branch version mid-run;
- every transitive reference must exist at the selected base commit;
- cycles in the cross-file reference graph are rejected; and
- later Git changes do not modify the run's bundle.

## Validation rules

The complete bundle is validated before a run is queued. Validation rejects:

- a missing child definition;
- a direct or transitive reference cycle;
- nesting deeper than the configured maximum;
- unknown input or output mapping names;
- missing required child inputs; and
- a template that cannot be resolved from the parent context.

When proposing several related definitions together, pass them in `proposed_related_workflows` so the server validates the intended bundle rather than only the currently merged children.

## Invocation visibility

A child is not flattened into the parent. It creates a durable invocation with:

- its own workflow ID and invocation path;
- a parent invocation and parent node execution;
- node executions, waves, attempts, and outputs; and
- its own completion state.

Run detail reconstructs this hierarchy from the immutable bundle plus durable invocation rows.

## Design recommendations

- Give reusable workflows small, explicit input and output contracts.
- Keep code-host checkpoints near the root unless the child genuinely owns the review boundary.
- Avoid leaking a large number of child outputs into the parent.
- Version parent and child changes in the same reviewed branch when their contract changes.
- Use catalog tags such as `reusable`, `quality`, or `delivery` for discoverability; tags have no execution semantics.
