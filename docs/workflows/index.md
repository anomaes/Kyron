---
title: Workflow authoring
description: Learn the structure, context model, and authoring lifecycle of Kyron workflows.
---

# Workflow authoring

A Kyron workflow is strict, versioned JSON stored with the repository it changes:

<span class="doc-path">.workflowEngine/[folders/]/&lt;workflow_id&gt;.json</span>

Workflow files can be organized into nested folders. Kyron mirrors that hierarchy in the
catalog while keeping workflow references ID-based. IDs must be unique across the entire
tree, and `.workflowEngine/templates/` remains reserved for node templates.

Definitions are code-reviewable, resolved from an exact Git commit, and immutable once captured in a run snapshot.

## Root structure

```json
{
  "id": "delivery",
  "name": "Feature delivery",
  "description": "Implement, verify, and present a change for review.",
  "version": 2,
  "created_by": "platform@example.com",
  "tags": ["delivery"],
  "inputs": {},
  "outputs": {},
  "variables": {},
  "nodes": [],
  "edges": [],
  "settings": {}
}
```

The filename stem must exactly equal `id`, including case. Identifiers start with an ASCII letter and then contain only letters, digits, and underscores. Unknown fields are validation errors at every level.

## Inputs

Inputs are values supplied by the caller when a root workflow is triggered or by a parent node when a child workflow is invoked.

```json
"inputs": {
  "TASK": {
    "type": "string",
    "required": true,
    "description": "The requested repository change"
  },
  "STRICT": {
    "type": "boolean",
    "required": false,
    "default": true
  }
}
```

Supported types are `string`, `integer`, `number`, and `boolean`. Root trigger values are type-checked, unknown names are rejected, and required inputs without a non-null default must be supplied.

## Variables and templates

`variables` defines non-secret public defaults:

```json
"variables": {
  "TEST_COMMAND": "pytest -q",
  "STRICT": true,
  "RETRY_COUNT": 2
}
```

Expand public values with exact `${NAME}` syntax in supported fields:

```json
"command": "${TEST_COMMAND}"
```

An unknown name fails execution; it is not left as literal text. Templates are intentionally not expanded in IDs, labels, executable paths, providers, models, skills, or interpreter names.

Secrets use native environment syntax such as `$NPM_TOKEN`, never `${NPM_TOKEN}`. See [variables and outputs](/reference/variables) for the full built-in list and precedence.

## Outputs

A workflow can expose values to its parent invocation:

```json
"outputs": {
  "TEST_EXIT_CODE": {
    "type": "string",
    "source": "${NODE_tests_EXIT_CODE}",
    "description": "Exit code from the test node"
  }
}
```

Output sources expand when the invocation completes. The current runtime renders outputs as strings, even if another type is declared. Prefer `string` for generated outputs unless the declaration is used only as catalog metadata.

## Nodes and edges

Nodes perform work or control execution. Edges establish dependencies and optional conditions. The graph must be acyclic. Repetition belongs in a bounded [review loop](/workflows/review-loops).

Start with:

- [Node types](/workflows/node-types)
- [Edges, conditions, and joins](/workflows/edges-and-joins)
- [Composition](/workflows/composition)
- [Example library](/workflows/examples)

## Settings

Workflow settings control checkpoint and safety limits:

| Setting | Default | Purpose |
| --- | --- | --- |
| `pi` | `{}` | Workflow-wide provider, model, and repository skill defaults |
| `auto_commit_after_wave` | `true` | Commit every successful process wave |
| `wave_commit_message_template` | `workflow(${WORKFLOW_ID}): wave ${WAVE_INDEX}` | Per-wave Git message |
| `final_commit_message_template` | `workflow(${WORKFLOW_ID}): complete run ${RUN_ID}` | Final Git message |
| `mr_title_template` | `Workflow: ${WORKFLOW_NAME} (${RUN_ID_SHORT})` | Default change-request title |
| `timeout_per_node_seconds` | `1800` | Workflow-level process timeout |
| `max_review_iterations` | `5` | Default loop bound |
| `max_subworkflow_depth` | `8` | Invocation nesting bound |
| `max_output_variable_bytes` | `65536` | Bounded public output preview |
| `propagate_skips` | `false` | Skip propagation behavior |

Server-wide limits can further constrain workflow settings.

## Authoring lifecycle

1. Create or edit the complete JSON definition.
2. Validate it together with any proposed child definitions.
3. Save through Kyron or commit it through the normal repository process.
4. Merge it to the project default branch for catalog visibility.
5. Trigger a run and inspect the resolved snapshot SHA.

The [complete JSON specification](/workflow-json-authoring-spec) is the field-level contract. The Pydantic models and semantic validator remain authoritative if documentation and code ever disagree.
