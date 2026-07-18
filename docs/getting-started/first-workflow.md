---
title: Your first workflow
description: Create, validate, merge, and run a small Kyron workflow.
---

# Your first workflow

This workflow asks the coding agent to implement a small task, then runs a test command. It demonstrates inputs, template expansion, a dependency edge, and wave checkpoints without introducing review loops yet.

## 1. Add the workflow file

Create `.workflowEngine/implement_and_test.json` in a registered repository:

```json
{
  "id": "implement_and_test",
  "name": "Implement and test",
  "description": "Implement a task and verify it with the repository test suite.",
  "version": 2,
  "created_by": "platform@example.com",
  "tags": ["implementation", "quality"],
  "inputs": {
    "TASK": {
      "type": "string",
      "required": true,
      "description": "The change to implement"
    }
  },
  "outputs": {},
  "variables": {
    "TEST_COMMAND": "pytest -q"
  },
  "nodes": [
    {
      "id": "implement",
      "type": "prompt",
      "label": "Implement the task",
      "join": "and",
      "config": {
        "prompt": "Implement this task in the current repository: ${TASK}",
        "allow_failure": false,
        "project_trust": "never"
      },
      "position": { "x": 100, "y": 120 }
    },
    {
      "id": "tests",
      "type": "bash",
      "label": "Run tests",
      "join": "and",
      "config": {
        "command": "${TEST_COMMAND}",
        "allow_failure": false,
        "shell": "/bin/bash"
      },
      "position": { "x": 380, "y": 120 }
    }
  ],
  "edges": [
    {
      "id": "implement_to_tests",
      "source": "implement",
      "target": "tests"
    }
  ],
  "settings": {}
}
```

Change `TEST_COMMAND` to a safe command that exists in your repository. The command executes in the run worktree.

## 2. Validate it

You can open the workflow in Kyron's builder and choose **Validate**, or call the API:

```http
POST /api/projects/<project-id>/workflows/validate
Content-Type: application/json

{
  "workflow": { ...complete workflow object... },
  "proposed_related_workflows": {}
}
```

Validation checks the strict schema, identifiers, edges, acyclicity, template references, mappings, and transitive child graph. Warnings do not prevent a save; errors do.

## 3. Merge the definition

Workflow saves do not silently write the default branch. Kyron proposes the change through a provider change request and uses optimistic concurrency against the default-branch SHA you edited.

Merge the definition change, then refresh the workflow catalog. Only merged definitions appear as runnable workflows.

## 4. Trigger the run

Choose **Run**, select a base ref, and enter a `TASK` such as:

```text
Add a health-check unit test for the existing health endpoint.
```

Kyron resolves the base ref before it creates the durable run. The resolved SHA shown on run detail is the source of truth.

## 5. Read the result

The run has two waves because the dependency prevents the nodes from being ready together:

1. `implement` runs Pi and checkpoints its repository changes.
2. `tests` starts from that checkpoint and runs the test command.

Open the node attempts to inspect exit code and bounded stdout/stderr previews. Full output remains in the configured run-data root until retention cleanup.

## Make it production-ready

Before using this pattern on important repositories:

- pin or constrain the model used by the prompt node;
- use repository-specific verification commands;
- add a [human feedback checkpoint](/guides/review-and-feedback);
- add timeouts appropriate for the codebase;
- keep credentials out of workflow JSON; and
- test failure and [resume behavior](/guides/recovery) in a disposable branch.

Next, explore the [node reference](/workflows/node-types) or start from the [example library](/workflows/examples).
