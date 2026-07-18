---
title: Visual workflow builder
description: Create and update workflow definitions with Kyron's graph editor.
---

# Visual workflow builder

Kyron's builder is a structured editor for the same version 2 JSON accepted by the API. It does not create a separate database-only workflow format; every accepted change is proposed back to the repository.

![Kyron workflow builder with a multi-node delivery graph](/assets/screenshots/workflow-builder.png)

## Open a definition

Choose a project, open **Workflows**, and select a merged definition. The catalog is read from the project's default-branch commit and includes complete workflow definitions so child selectors and mappings are based on one coherent revision.

The revision strip shows the commit you are editing. Kyron uses it for optimistic concurrency when you save.

## Build the graph

Drag a node type from the palette onto the canvas:

- **Bash** for an inline shell command;
- **Script** for a repository-local Python script;
- **Prompt** for a Pi coding-agent task;
- **Human feedback** for an approval or comment checkpoint;
- **Sub-workflow** for one reusable child invocation; or
- **Review loop** for bounded initial/revision cycles.

Connect nodes from source to target. The builder prevents obvious invalid connections, while server validation remains authoritative.

## Configure nodes

Select a node to open the inspector. Common fields include:

- a unique identifier;
- a human-readable label;
- `and` or `or` join behavior; and
- type-specific configuration.

Composite nodes expose structured input and output mappings based on the selected child definitions. Advanced JSON remains available for exact configuration where appropriate.

## Configure edges

Select an edge to make it unconditional or attach one supported condition:

- source exit code comparison;
- source output contains text;
- repository-relative file exists; or
- public variable comparison.

Conditions belong to edges, not nodes. A target with multiple incoming edges applies its own join after every relevant edge is evaluated.

## Validate before saving

Validation covers both the root definition and any related drafts being edited together. Fix every error shown in the validation drawer. Common errors include:

- filename/workflow ID mismatch;
- duplicate node or edge IDs;
- an edge referencing a missing node;
- an ordinary cycle;
- missing or incompatible child inputs;
- invalid output mappings; and
- a public template name that cannot exist at that point.

## Save through review

**Save** sends the workflow plus `expected_base_commit_sha`. Kyron formats stable JSON, creates a branch, commits the definition, pushes it, and opens a GitLab merge request or GitHub pull request.

If the default branch moved since you loaded the editor, saving returns a conflict. Reload the current definition and deliberately reapply the change. Kyron does not silently overwrite a newer revision.

Deleting a definition follows the same reviewed flow and is blocked while another merged workflow references it.

## When to edit JSON directly

The builder is ideal for topology and common configuration. Direct JSON is often faster for large mappings, repeated conditions, or code-reviewed changes made alongside application code. Both paths use the same [workflow JSON specification](/workflow-json-authoring-spec).
