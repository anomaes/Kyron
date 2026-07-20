---
title: Visual workflow builder
description: Create and update workflow definitions with Kyron's graph editor.
---

# Visual workflow builder

Kyron's builder is a structured editor for the same version 2 JSON accepted by the API. Stored changes remain project-local until you deliberately create a code-host review.

![Kyron workflow builder with a multi-node delivery graph](/assets/screenshots/workflow-builder.png)

## Open a definition

Choose a project, open **Workflows**, and select a definition. The catalog starts from the project's exact default-branch commit, then overlays locally stored and in-review definitions.

The revision strip shows the base commit you are editing. It also shows outgoing and in-review counts. Kyron uses the base commit for optimistic concurrency when you store or review changes.

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

## Reuse node templates

Select a configured node and choose **Store as template**. Give the template a stable ID, name, and optional description. Templates are scoped to the project and follow the same local-store and review lifecycle as workflows.

Open **Templates** in the left palette to browse them. Inserting a template clones its type, label, join, and configuration while assigning a unique node ID and a new canvas position. Later edits do not mutate the source template.

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

## Store locally, review deliberately

**Store** sends the workflow plus `expected_base_commit_sha`. Kyron validates and formats stable JSON in the project's local change layer. It does not commit, push, or open a review.

The workflow catalog shows the number of outgoing changes. **Create review** batches all outgoing workflows and templates into one commit and opens one GitLab merge request or GitHub pull request. New changes can update that review instead of creating save-by-save history.

If the default branch moved since you loaded the editor, storing or reviewing returns a conflict. Reload the current definition and deliberately reapply the change. Kyron does not silently overwrite a newer revision.

When local changes exist, the Run dialog can use them for a local definition test. Kyron creates an exact local Git snapshot for reproducibility. The run never pushes or creates a code-host review, so its worktree and results stay on the Kyron host.

Deleting a definition follows the same local-store and batch-review flow and is blocked while another visible workflow references it.

## When to edit JSON directly

The builder is ideal for topology and common configuration. Direct JSON is often faster for large mappings, repeated conditions, or code-reviewed changes made alongside application code. Both paths use the same [workflow JSON specification](/workflow-json-authoring-spec).
